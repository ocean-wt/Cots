"""Proof of durable checkpoint recovery.

A run whose final node crashes is continued on a *fresh runtime/bus* (the
in-process equivalent of a process restart, using the MySQL checkpointer).
The expert nodes must NOT be re-executed: the agent's real tool runs exactly
once because its completed superstep is replayed from the checkpoint.

Runs only against MySQL (the checkpointer is MySQL-backed).
"""

import asyncio

import pytest

from app.agents import supervisor as supervisor_mod
from app.agents.context import Identity
from app.agents.runtime import AgentRuntime
from app.agents.synthesizer import synthesize_and_stream
from app.agents.tools import log_tools
from app.core.config import settings
from app.db.models import DynamicWorkflowState
from app.db.session import AsyncSessionLocal
from app.services.container import container
from app.services.redis_client import get_redis
from tests.helpers import by_event

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("mysql"),
    reason="durable checkpoint resume requires the MySQL checkpointer",
)


async def _snapshot(run_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            DynamicWorkflowState.__table__.select().where(
                DynamicWorkflowState.run_id == run_id)
        )).first()
        if row is None:
            return {}
        return row._mapping["state_snapshot"] or {}


async def test_resume_from_checkpoint_does_not_recompute_experts(monkeypatch):
    redis_client = get_redis()
    counter_key = "cpts:diag:resume-test"
    await redis_client.delete(counter_key)

    real_analyze = log_tools.analyze_trace
    real_synth = synthesize_and_stream
    synth_calls = {"n": 0}

    async def counting_analyze(trace_id):
        await redis_client.incr(counter_key)
        return await real_analyze(trace_id)

    async def flaky_synth(**kwargs):
        synth_calls["n"] += 1
        if synth_calls["n"] == 1:
            raise RuntimeError("simulated synthesize crash")
        return await real_synth(**kwargs)

    monkeypatch.setattr(log_tools, "analyze_trace", counting_analyze)
    monkeypatch.setattr(supervisor_mod, "synthesize_and_stream", flaky_synth)

    runtime1 = AgentRuntime(container.trace_writer)
    ctx1 = await runtime1.run(
        "系统报 429 了 trc-9f3a2c7b1e4d 紧急排查",
        identity=Identity(),
    )
    run_id = ctx1.run_id

    # Phase 1 ends with the crash error event.
    phase1 = []
    async for event in ctx1.bus.stream():
        phase1.append(event)
        if event.event in ("error", "done"):
            break
    assert by_event(phase1, "error"), "phase 1 must end with the crash"
    assert by_event(phase1, "final") == [], "no report before crash"

    tool_runs_after_crash = int(await redis_client.get(counter_key) or 0)
    assert tool_runs_after_crash == 1

    # ---- simulate a new process: fresh runtime continues the same thread ----
    snapshot = await _snapshot(run_id)
    assert snapshot.get("goal"), "checkpoint metadata must survive"

    # give the MySQL connection a moment to release the failed superstep lock
    await asyncio.sleep(0.5)

    runtime2 = AgentRuntime(container.trace_writer)
    ctx2 = await runtime2.resume(run_id, identity=Identity(), snapshot=snapshot)

    phase2 = []
    async for event in ctx2.bus.stream():
        phase2.append(event)
        if event.event in ("done", "error"):
            break

    finals = by_event(phase2, "final")
    assert len(finals) == 1, [e.event for e in phase2]
    report = finals[0].payload["report"]
    assert report["root_causes"], report

    # THE invariant: completed expert supersteps are replayed from checkpoint,
    # never re-executed.
    tool_runs_total = int(await redis_client.get(counter_key) or 0)
    assert tool_runs_total == 1, (
        f"expert tool ran {tool_runs_total} times after resume "
        "(checkpoint replay violated)"
    )
    # synthesize itself ran once more (the crashed node legitimately retries).
    assert synth_calls["n"] == 2
