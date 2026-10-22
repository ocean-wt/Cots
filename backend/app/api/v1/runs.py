"""Workflow run observability and retry (restart recovery)."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agents.context import Identity
from app.agents.runtime import AgentRuntime
from app.api.deps import Principal, get_principal
from app.db.models import DynamicWorkflowState
from app.db.session import AsyncSessionLocal
from app.services.container import container
from app.api.v1.chat import _event_stream

router = APIRouter()
RUN_ID_RE = re.compile(r"^run-[a-f0-9]{8,32}$")


class RetryRequest(BaseModel):
    pass


@router.get("/runs")
async def list_runs(
    limit: int = 30,
    principal: Principal = Depends(get_principal),
) -> dict:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(DynamicWorkflowState)
                .order_by(DynamicWorkflowState.id.desc())
                .limit(limit)
            )
        ).all()
        return {
            "items": [
                {
                    "run_id": r.run_id,
                    "trace_id": r.trace_id,
                    "status": r.status,
                    "current_node": r.current_node,
                    "round": r.round_index,
                    "goal": (r.state_snapshot or {}).get("goal", ""),
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        }


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: str,
    principal: Principal = Depends(get_principal),
):
    """Re-execute the original goal of an interrupted run as a fresh SSE run."""
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")

    async with AsyncSessionLocal() as session:
        state = await session.scalar(
            select(DynamicWorkflowState).where(DynamicWorkflowState.run_id == run_id)
        )
        if state is None:
            raise HTTPException(status_code=404, detail="run not found")
        goal = (state.state_snapshot or {}).get("goal")
        if not goal:
            raise HTTPException(status_code=422, detail="run has no goal to retry")

    runtime = AgentRuntime(container.trace_writer)
    ctx = await runtime.run(
        goal=goal,
        identity=Identity(
            tenant_id=principal.tenant_id,
            tenant_code=principal.tenant_code,
            user_id=principal.user_id,
            email=principal.email,
        ),
        inbound_trace_id=principal.trace_id,
    )
    container.register_run(ctx.run_id, ctx.bus)
    return EventSourceResponse(
        _event_stream(ctx.bus, ctx.run_id, 0),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Retry-Of": run_id,
            "X-Run-Id": ctx.run_id,
        },
        ping=15,
    )
