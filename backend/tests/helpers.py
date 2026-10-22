"""Helpers for driving a full agent run and collecting its SSE events."""

from app.agents.context import Identity
from app.agents.events import AgentEvent
from app.agents.runtime import AgentRuntime
from app.services.container import container


async def collect_run(
    goal: str,
    identity: Identity | None = None,
    inbound_trace_id: str | None = None,
) -> list[AgentEvent]:
    runtime = AgentRuntime(container.trace_writer)
    ctx = await runtime.run(
        goal=goal,
        identity=identity or Identity(),
        inbound_trace_id=inbound_trace_id,
    )
    events: list[AgentEvent] = []
    async for event in ctx.bus.stream():
        events.append(event)
    return events


def by_event(events: list[AgentEvent], name: str) -> list[AgentEvent]:
    return [e for e in events if e.event == name]


def actions_by_agent(events: list[AgentEvent]) -> dict[str, list[AgentEvent]]:
    grouped: dict[str, list[AgentEvent]] = {}
    for event in by_event(events, "agent_action"):
        grouped.setdefault(event.payload["agent"], []).append(event)
    return grouped
