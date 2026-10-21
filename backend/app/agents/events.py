"""SSE event bus bridging agent-node execution to the streaming API.

A single append-only history guarded by an async condition: every live
subscriber tracks the last sequence it received, so reconnects (``after_seq``)
replay from history and a run with several consumers never double-delivers.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    event: str
    seq: int = 0
    ts: float = field(default_factory=lambda: time.time())
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("event")
        return data


class EventBus:
    def __init__(self, start_seq: int = 0) -> None:
        # Continuation buses (crash resume) number above the already
        # journaled events so SSE ids stay globally monotonic for a run.
        self._condition = asyncio.Condition()
        self._seq = start_seq
        self.history: list[AgentEvent] = []
        self.closed = False

    async def publish(self, event: str, **payload: Any) -> AgentEvent:
        async with self._condition:
            self._seq += 1
            agent_event = AgentEvent(event=event, seq=self._seq, payload=payload)
            self.history.append(agent_event)
            self._condition.notify_all()
        return agent_event

    async def stream(self, after_seq: int = 0) -> AsyncIterator[AgentEvent]:
        sent = after_seq
        while True:
            async with self._condition:
                if sent < len(self.history):
                    event = self.history[sent]
                    sent += 1
                    should_stop = self.closed and sent == len(self.history)
                else:
                    if self.closed:
                        return
                    await self._condition.wait()
                    continue
            yield event
            if should_stop:
                return

    def close(self) -> None:
        async def _notify() -> None:
            async with self._condition:
                self.closed = True
                self._condition.notify_all()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify())
        except RuntimeError:
            self.closed = True
