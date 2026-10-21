"""Typed contracts exchanged across the multi-agent system."""

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["supervisor", "diagnostic", "billing", "knowledge", "support"]


class SubTask(BaseModel):
    id: str
    agent: AgentName
    goal: str
    tool_hint: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class Plan(BaseModel):
    intent: str
    summary: str
    subtasks: list[SubTask] = Field(default_factory=list)
    need_ticket: bool = False
    reasoning: str = ""


class Evidence(BaseModel):
    id: str
    kind: Literal["log", "billing", "knowledge", "ticket", "system"]
    title: str
    summary: str
    source: str
    agent: str
    status: str = "ok"  # ok|empty|error|timeout
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentVerdict(BaseModel):
    agent: str
    status: Literal["ok", "empty", "error", "timeout"] = "ok"
    summary: str = ""
    evidences: list[Evidence] = Field(default_factory=list)
    requests_ticket: bool = False
    confidence: float = 0.0
    duration_ms: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)
    error: str = ""


class FinalReport(BaseModel):
    trace_id: str
    run_id: str
    intent: str
    conclusion_markdown: str
    root_causes: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    evidences: list[Evidence] = Field(default_factory=list)
    tickets: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    rounds: int = 1
    token_usage: dict[str, int] = Field(default_factory=dict)
    # True when counts come from tiktoken estimation rather than a
    # provider-exact usage receipt on the streamed completion.
    token_usage_estimated: bool = True
