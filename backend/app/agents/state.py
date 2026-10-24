"""Shared LangGraph state.

Every field is JSON-serializable on purpose: the durable MySQL checkpointer
persists state between process restarts. Runtime-only objects (event bus,
trace writer) travel through app.agents.runtime_ctx, never through state.
Typed pydantic objects (SubTask / AgentVerdict) cross node boundaries as
plain dicts and are validated back inside the nodes that need them.
"""

from typing import Annotated, Any, TypedDict


def _merge_lists(left: list, right: list) -> list:
    return (left or []) + (right or [])


class CotsState(TypedDict, total=False):
    goal: str
    trace_id: str
    conversation_id: int | None
    history: list[dict[str, str]]

    intent: str
    # Full plan dict: {"intent","summary","subtasks":[...]} — replaced on
    # each round (escalation), so it has no append reducer.
    plan: dict[str, Any]
    # list[dict] of schemas.AgentVerdict
    verdicts: Annotated[list[dict[str, Any]], _merge_lists]
    # list[dict] of schemas.Evidence
    evidences: Annotated[list[dict[str, Any]], _merge_lists]
    # created tickets [{ticket_no,...}]
    tickets: Annotated[list[dict[str, Any]], _merge_lists]

    round: int
    max_rounds: int
    root_causes: Annotated[list[str], _merge_lists]
    steps: Annotated[list[str], _merge_lists]
