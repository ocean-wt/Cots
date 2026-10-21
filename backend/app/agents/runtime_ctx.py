"""Per-run execution context resolution.

LangGraph executes node functions on its own Pregel tasks, which do not
reliably inherit a ContextVar set inside the driver task (it breaks under
concurrent runs). The authoritative mechanism is therefore a run registry
keyed by the checkpoint thread_id, which is delivered to every node via
``config["configurable"]["thread_id"]``. A ContextVar remains as a fallback
for non-graph code paths.
"""

import contextvars
from typing import Optional

from langchain_core.runnables.config import RunnableConfig

from app.agents.context import RunContext

_current_ctx: contextvars.ContextVar[Optional[RunContext]] = contextvars.ContextVar(
    "cots_run_ctx", default=None
)

_REGISTRY: dict[str, RunContext] = {}


def register_run_ctx(ctx: RunContext) -> None:
    _REGISTRY[ctx.run_id] = ctx
    _current_ctx.set(ctx)


def unregister_run_ctx(run_id: str) -> None:
    _REGISTRY.pop(run_id, None)


def set_run_ctx(ctx: RunContext) -> contextvars.Token:
    return _current_ctx.set(ctx)


def _thread_id(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    return (config.get("configurable") or {}).get("thread_id")


def get_run_ctx(config: RunnableConfig | None = None) -> RunContext:
    run_id = _thread_id(config)
    if run_id and run_id in _REGISTRY:
        return _REGISTRY[run_id]
    ctx = _current_ctx.get()
    if ctx is not None:
        return ctx
    raise RuntimeError("no active run context (drive task not started?)")
