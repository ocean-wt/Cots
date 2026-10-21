"""Runtime context shared by every node/agent of one supervisor run."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.events import EventBus
from app.services.trace_writer import TraceWriter


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:16]}"


def new_trace_id() -> str:
    return f"trc-{uuid.uuid4().hex[:12]}"


@dataclass
class Identity:
    tenant_id: int = 1
    tenant_code: str = "acme"
    user_id: int = 1
    email: str = "ops@acme.example"


@dataclass
class TokenCounter:
    prompt: int = 0
    completion: int = 0
    total: int = 0

    def add(self, prompt: int = 0, completion: int = 0) -> None:
        self.prompt += prompt
        self.completion += completion
        self.total += prompt + completion

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt,
            "completion_tokens": self.completion,
            "total_tokens": self.total,
        }


@dataclass
class RunContext:
    run_id: str
    trace_id: str
    identity: Identity
    bus: EventBus
    trace_writer: TraceWriter
    goal: str = ""
    conversation_id: int | None = None
    round_index: int = 0
    tokens: TokenCounter = field(default_factory=TokenCounter)

    async def emit(self, event: str, **payload: Any):
        """Publish to the live SSE stream."""
        return await self.bus.publish(event, trace_id=self.trace_id,
                                      run_id=self.run_id, **payload)

    async def trace(
        self,
        agent: str,
        node: str,
        phase: str,
        action: str = "",
        detail: str = "",
        task_id: str | None = None,
        input_payload: dict | None = None,
        output_payload: dict | None = None,
        evidence: dict | None = None,
        token_usage: dict | None = None,
        status: str = "ok",
        duration_ms: int = 0,
    ) -> None:
        """Persist one execution trace asynchronously (never blocks the run)."""
        await self.trace_writer.enqueue({
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "tenant_id": self.identity.tenant_id,
            "conversation_id": self.conversation_id,
            "round_index": self.round_index,
            "task_id": task_id,
            "agent_name": agent,
            "node": node,
            "phase": phase,
            "action": action,
            "detail": detail,
            "input_payload": input_payload or {},
            "output_payload": output_payload or {},
            "evidence": evidence or {},
            "token_usage": token_usage or {},
            "status": status,
            "duration_ms": duration_ms,
        })

    async def agent_action(
        self,
        agent: str,
        status: str,
        action: str,
        detail: str = "",
        task_id: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        """Stream the pipeline visualization event AND persist its trace."""
        await self.emit(
            "agent_action",
            agent=agent,
            status=status,
            action=action,
            detail=detail,
            task_id=task_id,
            round=self.round_index,
            tools=tools or [],
        )
        await self.trace(
            agent=agent,
            node=agent,
            phase=status,
            action=action,
            detail=detail,
            task_id=task_id,
            output_payload={"tools": tools or []},
            status="ok" if status not in {"error", "timeout"} else status,
        )


@dataclass
class StepTimer:
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)
