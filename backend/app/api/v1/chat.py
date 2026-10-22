"""Chat SSE endpoint — the live window into the multi-agent run."""

import json
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agents.context import Identity
from app.agents.runtime import AgentRuntime
from app.api.deps import Principal, get_principal
from app.core.config import settings
from app.core.sanitize import clean_text
from app.core.telemetry import count_tokens
from app.db.models import Conversation, Message
from app.db.session import AsyncSessionLocal
from app.services.container import container
from app.services.event_journal import append_event, replay_events

router = APIRouter()

RUN_ID_RE = re.compile(r"^run-[a-f0-9]{8,32}$")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None

    @field_validator("message")
    @classmethod
    def _harden(cls, value: str) -> str:
        cleaned = clean_text(value, settings.INPUT_MAX_CHARS).strip()
        if not cleaned:
            raise ValueError("message is empty after sanitization")
        return cleaned


async def _ensure_conversation(
    principal: Principal, request: ChatRequest
) -> tuple[int, list[dict[str, str]]]:
    async with AsyncSessionLocal() as session:
        conversation = None
        if request.conversation_id:
            conversation = await session.get(Conversation, request.conversation_id)
        if conversation is None or conversation.tenant_id != principal.tenant_id:
            conversation = Conversation(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                title=request.message[:40],
                status="active",
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)

        session.add(Message(
            conversation_id=conversation.id,
            role="user",
            content=request.message,
            token_usage={"total_tokens": count_tokens(request.message)},
        ))
        if conversation.title == "新会话":
            conversation.title = request.message[:40]
        await session.commit()

        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.id.desc())
                .limit(10)
            )
        ).all()
        history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
        return conversation.id, history


async def _event_stream(bus, run_id: str, after_seq: int):
    """Emit SSE events, journaling each for resume; sse-starlette pings too."""
    async for event in bus.stream(after_seq=after_seq):
        await append_event(run_id, event.seq, event.event, event.payload)
        yield {
            "id": str(event.seq),
            "event": event.event,
            "data": json.dumps(event.payload, ensure_ascii=False, default=str),
        }


async def _start_stream(body: ChatRequest, principal: Principal):
    conversation_id, history = await _ensure_conversation(principal, body)
    runtime = AgentRuntime(container.trace_writer)
    ctx = await runtime.run(
        goal=body.message,
        identity=Identity(
            tenant_id=principal.tenant_id,
            tenant_code=principal.tenant_code,
            user_id=principal.user_id,
            email=principal.email,
        ),
        conversation_id=conversation_id,
        history=history,
        inbound_trace_id=principal.trace_id,
    )
    container.register_run(ctx.run_id, ctx.bus)
    return ctx


def _sse_response(ctx, after_seq: int = 0):
    return EventSourceResponse(
        _event_stream(ctx.bus, ctx.run_id, after_seq),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": ctx.trace_id,
            "X-Run-Id": ctx.run_id,
        },
        ping=15,
    )


@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    principal: Principal = Depends(get_principal),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="client disconnected")
    ctx = await _start_stream(body, principal)
    after_seq = int(last_event_id) if (last_event_id or "").isdigit() else 0
    return _sse_response(ctx, after_seq)


@router.get("/stream/{run_id}/resume")
async def chat_stream_resume(
    run_id: str,
    last_event_id: int = 0,
    principal: Principal = Depends(get_principal),
):
    """Reconnect — three cases:

    1. live run: replay missed journaled events, then tail the live bus;
    2. crashed run with a durable checkpoint: continue execution from the
       last completed node on a new bus (true resume, not a fresh run);
    3. finished run whose journal expired: rebuild final/done from MySQL.
    """
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")

    bus = container.get_run(run_id)
    missed = await replay_events(run_id, last_event_id)

    if (bus is None or bus.closed) and not _has_terminal(missed):
        from app.db.models import DynamicWorkflowState

        async with AsyncSessionLocal() as session:
            wf = await session.scalar(
                select(DynamicWorkflowState).where(
                    DynamicWorkflowState.run_id == run_id)
            )
        if wf is not None and wf.status != "completed":
            # Continue execution from the durable checkpoint.
            runtime = AgentRuntime(container.trace_writer)
            continue_ctx = await runtime.resume(
                run_id,
                identity=Identity(
                    tenant_id=principal.tenant_id,
                    tenant_code=principal.tenant_code,
                    user_id=principal.user_id,
                    email=principal.email,
                ),
                snapshot=wf.state_snapshot or {},
                inbound_trace_id=principal.trace_id,
            )
            container.register_run(run_id, continue_ctx.bus)
            bus = continue_ctx.bus
        elif not missed:
            # Journal expired: rebuild the final report from MySQL.
            report = await _load_final_report(run_id, principal.tenant_id)
            if report is None:
                raise HTTPException(status_code=404,
                                    detail="run not found or expired")
            missed = [{"seq": 1, "event": "final", "data": {"report": report}},
                      {"seq": 2, "event": "done", "data": {}}]

    async def _generator():
        emitted_until = last_event_id
        for item in missed:
            emitted_until = max(emitted_until, item["seq"])
            yield {
                "id": str(item["seq"]),
                "event": item["event"],
                "data": json.dumps(item["data"], ensure_ascii=False, default=str),
            }
        if bus is not None and not bus.closed:
            # Continuation buses number above the old journal; filter anyway.
            async for event in bus.stream(after_seq=0):
                if event.seq <= emitted_until:
                    continue
                await append_event(run_id, event.seq, event.event, event.payload)
                yield {
                    "id": str(event.seq),
                    "event": event.event,
                    "data": json.dumps(event.payload, ensure_ascii=False,
                                       default=str),
                }

    return EventSourceResponse(_generator(), headers={"X-Run-Id": run_id}, ping=15)


def _has_terminal(events: list[dict]) -> bool:
    return any(e.get("event") in ("final", "done", "error") for e in events)


async def _load_final_report(run_id: str, tenant_id: int) -> dict | None:
    """Recover a finished run's final report from the persisted message."""
    async with AsyncSessionLocal() as session:
        conversation = (
            await session.scalars(
                select(Conversation)
                .where(Conversation.tenant_id == tenant_id)
                .order_by(Conversation.id.desc())
                .limit(50)
            )
        ).all()
        convo_ids = [c.id for c in conversation]
        if not convo_ids:
            return None
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id.in_(convo_ids))
                .where(Message.role == "assistant")
                .order_by(Message.id.desc())
                .limit(100)
            )
        ).all()
        for row in rows:
            structured = row.structured or {}
            if structured.get("run_id") == run_id:
                return structured
    return None
