"""AgentRuntime — drives supervisor runs and bridges events to SSE.

Durability:
* with a MySQL DSN the graph runs on a per-run AIOMySQLSaver checkpointer
  (thread_id == run_id); every completed node is persisted, so a crashed run
  continues from its last completed node via ``resume()`` instead of rerunning.
* with no MySQL (SQLite tests) it runs without a checkpointer.
"""

import asyncio

from app.agents.context import Identity, RunContext, new_run_id, new_trace_id
from app.agents.events import EventBus
from app.agents.graph import build_graph
from app.agents.runtime_ctx import register_run_ctx, unregister_run_ctx
from app.core.config import settings
from app.core.logging import get_logger
from app.services.event_journal import journal_length
from app.services.trace_writer import TraceWriter

logger = get_logger(__name__)


class AgentRuntime:
    def __init__(self, trace_writer: TraceWriter) -> None:
        self.trace_writer = trace_writer

    async def run(
        self,
        goal: str,
        identity: Identity | None = None,
        conversation_id: int | None = None,
        history: list[dict[str, str]] | None = None,
        inbound_trace_id: str | None = None,
        run_id: str | None = None,
    ) -> RunContext:
        bus = EventBus()
        ctx = RunContext(
            run_id=run_id or new_run_id(),
            trace_id=inbound_trace_id or new_trace_id(),
            identity=identity or Identity(),
            bus=bus,
            trace_writer=self.trace_writer,
            goal=goal,
            conversation_id=conversation_id,
        )

        initial_state = {
            "goal": goal,
            "trace_id": ctx.trace_id,
            "conversation_id": conversation_id,
            "history": history or [],
            "round": 0,
            "max_rounds": settings.AGENT_MAX_ROUNDS,
            "verdicts": [],
            "evidences": [],
            "tickets": [],
            "root_causes": [],
            "steps": [],
        }
        config = {
            "configurable": {"thread_id": ctx.run_id},
            "recursion_limit": settings.AGENT_MAX_ROUNDS * 3 + 6,
        }
        self._spawn_driver(ctx, initial_state, config)
        return ctx

    async def resume(
        self,
        run_id: str,
        identity: Identity | None = None,
        snapshot: dict | None = None,
        inbound_trace_id: str | None = None,
    ) -> RunContext:
        """Continue a crashed run from its checkpoint on a fresh bus."""
        snapshot = snapshot or {}
        start_seq = await journal_length(run_id)
        bus = EventBus(start_seq=start_seq)
        ctx = RunContext(
            run_id=run_id,
            trace_id=inbound_trace_id or snapshot.get("trace_id") or new_trace_id(),
            identity=identity or Identity(),
            bus=bus,
            trace_writer=self.trace_writer,
            goal=snapshot.get("goal", ""),
            conversation_id=snapshot.get("conversation_id"),
        )
        await ctx.agent_action(
            "supervisor", "planning",
            "检测到上次运行中断，正在从最后完成的检查点继续",
        )
        config = {
            "configurable": {"thread_id": run_id},
            "recursion_limit": settings.AGENT_MAX_ROUNDS * 3 + 6,
        }
        # None input: resume the checkpointed thread, executing only the
        # pending (non-completed) supersteps.
        self._spawn_driver(ctx, None, config)
        return ctx

    # Strong references to in-flight driver tasks: without these the loop
    # only keeps a weak ref and concurrent tasks can be garbage-collected
    # mid-run (which would close the bus and silently deliver zero events).
    _drivers: set = set()

    # ------------------------------------------------------------------ #
    def _spawn_driver(self, ctx: RunContext, initial_state: dict | None,
                      config: dict) -> None:
        async def _drive() -> None:
            register_run_ctx(ctx)
            try:
                async with saver_cm() as saver:
                    graph = build_graph(saver)
                    await graph.ainvoke(initial_state, config=config)
                await ctx.emit("done")
            except Exception as exc:
                code, retriable = _classify(exc)
                logger.exception("agent run failed: %s", exc)
                await ctx.emit(
                    "error",
                    code=code,
                    retriable=retriable,
                    message=f"{type(exc).__name__}: {exc}"[:600],
                )
            finally:
                unregister_run_ctx(ctx.run_id)
                ctx.bus.close()

        task = asyncio.ensure_future(_drive())
        self._drivers.add(task)
        task.add_done_callback(self._drivers.discard)


_saver_setup_lock = asyncio.Lock()
_saver_ready = False


async def ensure_saver_schema() -> None:
    """Create checkpointer tables once per process.

    Concurrent drivers must not each call saver.setup(): its migration insert
    races on checkpoint_migrations' primary key.
    """
    global _saver_ready
    if _saver_ready or not settings.DATABASE_URL.startswith("mysql"):
        return
    async with _saver_setup_lock:
        if _saver_ready:
            return
        import aiomysql
        from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

        kwargs = AIOMySQLSaver.parse_conn_string(settings.DATABASE_URL)
        conn = await aiomysql.connect(**kwargs, autocommit=True, charset="utf8mb4")
        try:
            await AIOMySQLSaver(conn).setup()
        finally:
            conn.close()
        _saver_ready = True


def saver_cm():
    """Per-run MySQL checkpointer connection (or null for SQLite).

    The platform standardizes on utf8mb4_0900_ai_ci (MySQL 8 default): the
    saver's JSON_TABLE columns always use the charset-default collation, so a
    non-default DB collation raises "Illegal mix of collations".
    """
    if not settings.DATABASE_URL.startswith("mysql"):
        return _null_saver()
    import contextlib

    import aiomysql
    from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

    kwargs = AIOMySQLSaver.parse_conn_string(settings.DATABASE_URL)

    @contextlib.asynccontextmanager
    async def _cm():
        await ensure_saver_schema()
        conn = await aiomysql.connect(
            **kwargs,
            autocommit=True,
            charset="utf8mb4",
        )
        try:
            yield AIOMySQLSaver(conn)
        finally:
            conn.close()

    return _cm()


class _null_saver:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _classify(exc: Exception) -> tuple[str, bool]:
    """Map exceptions to stable, client-actionable error codes."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "AGENT_TIMEOUT", True
    if "connection" in name or "connect" in text or "unavailable" in text:
        return "DEPENDENCY_UNAVAILABLE", True
    if "milvus" in text or "redis" in text or "mysql" in text:
        return "DEPENDENCY_ERROR", True
    return "AGENT_INTERNAL_ERROR", False
