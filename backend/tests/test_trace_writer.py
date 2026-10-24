"""Durable async trace writing into agent_execution_traces."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.db.models import AgentExecutionTrace
from app.db.session import AsyncSessionLocal
from app.services.trace_writer import pending_count, written_count

pytestmark = pytest.mark.usefixtures("stack")


async def test_traces_persisted_without_loss():
    run_id = "run-trace-lossless-test"
    from app.services.container import container

    for i in range(5):
        await container.trace_writer.enqueue({
            "run_id": run_id,
            "trace_id": f"trc-trace-{i}",
            "tenant_id": 1,
            "agent_name": "diagnostic",
            "node": "diagnostic",
            "phase": "tool_result",
            "action": "analyze_trace",
            "output_payload": {"index": i},
            "token_usage": {"total_tokens": i},
            "status": "ok",
        })

    deadline = 20
    while deadline > 0:
        written = await written_count(run_id)
        queued = await pending_count()
        if written == 5 and queued == 0:
            break
        await asyncio.sleep(0.2)
        deadline -= 1

    written = await written_count(run_id)
    queued = await pending_count()
    assert written == 5, f"expected 5 rows, got {written}"
    assert queued == 0, f"queue not drained: {queued}"

    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(AgentExecutionTrace)
                .where(AgentExecutionTrace.run_id == run_id)
                .order_by(AgentExecutionTrace.id)
            )
        ).all()
        assert [r.trace_id for r in rows] == [f"trc-trace-{i}" for i in range(5)]
        assert all(r.token_usage["total_tokens"] == idx
                   for idx, r in enumerate(rows))
