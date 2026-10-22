"""Reliability/chaos tests: concurrency, Redis flap, tool failure, hostile input.

Every fault is injected against a real component (real subprocess Redis,
real asyncio concurrency, real ASGI app) — no business logic is mocked.
"""

import asyncio
import os
import subprocess
import time

import httpx
import pytest
import redis as redis_sync
from sqlalchemy import select

from app.agents.tools import billing_tools
from app.core.config import settings
from app.db.models import AgentExecutionTrace, DynamicWorkflowState
from app.db.session import AsyncSessionLocal
from app.main import app
from app.retrieval.service import HybridRetrievalService
from app.services.reconciliation import reconcile_interrupted_runs
from app.services.trace_writer import TraceWriter
from tests.helpers import by_event, collect_run

pytestmark = pytest.mark.usefixtures("stack")

REDIS_BIN = "/usr/local/bin/redis-server72"
REDIS_CLI = "/usr/local/bin/redis-cli72"


@pytest.fixture
def uuid_ns():
    import uuid
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- concurrency
async def test_concurrent_runs_are_isolated():
    specs = [
        ("429 限流排查 trc-9f3a2c7b1e4d", "trc-concurrent-a"),
        ("租户 QPS 被限制是不是欠费了", "trc-concurrent-b"),
        ("webhook 回调如何配置签名", "trc-concurrent-c"),
        ("如何配置 API Key 权限", "trc-concurrent-d"),
    ]

    async def one(goal: str, trace_id: str):
        return trace_id, await collect_run(goal, inbound_trace_id=trace_id)

    results = await asyncio.gather(*[one(g, t) for g, t in specs])

    for trace_id, events in results:
        finals = by_event(events, "final")
        assert len(finals) == 1
        report = finals[0].payload["report"]
        assert report["trace_id"] == trace_id
        # no foreign trace id leaked into this run's evidence
        serialized = str(by_event(events, "evidence"))
        others = [t for _, t in specs if t != trace_id]
        assert not any(t in serialized for t in others)


async def test_rebuild_coalesces_under_concurrency():
    service = HybridRetrievalService.instance()
    results = await asyncio.gather(*[service.rebuild() for _ in range(4)])
    assert all(r["chunks"] == 12 and r["vectors"] == 12 for r in results)


# ------------------------------------------------------------ Redis flap test
@pytest.mark.skipif(not os.path.exists(REDIS_BIN), reason="redis72 binary required")
async def test_traces_lossless_during_redis_outage(tmp_path, uuid_ns):
    port = 6399
    subprocess.run(
        [REDIS_BIN, "--daemonize", "yes", "--port", str(port),
         f"--dir", str(tmp_path), "--save", "", "--appendonly", "no"],
        check=True, capture_output=True,
    )
    time.sleep(0.5)
    client = redis_sync.asyncio.from_url(
        f"redis://127.0.0.1:{port}/15", decode_responses=True
    )
    writer = TraceWriter(redis_client=client)
    await writer.start()

    async def enqueue(prefix: str, n: int):
        for i in range(n):
            await writer.enqueue({
                "run_id": f"run-flap-{prefix}-{uuid_ns}",
                "trace_id": f"trc-flap-{prefix}-{i}",
                "tenant_id": 1, "agent_name": "diagnostic", "node": "n",
                "phase": "end", "action": "a",
            })

    await enqueue("before", 5)
    deadline = 20
    while deadline:
        if await _count("run-flap-before") == 5:
            break
        await asyncio.sleep(0.2)
        deadline -= 1
    assert await _count("run-flap-before") == 5

    # Kill Redis: enqueues must fall back to direct, durable MySQL writes.
    subprocess.run([REDIS_CLI, "-p", str(port), "shutdown", "nosave"],
                   capture_output=True)
    await asyncio.sleep(0.5)
    assert writer.redis_alive is False
    await enqueue("during", 5)
    await asyncio.sleep(0.3)
    assert await _count("run-flap-during") == 5

    # Redis recovers: writer reconnects and the queue path works again.
    subprocess.run(
        [REDIS_BIN, "--daemonize", "yes", "--port", str(port),
         f"--dir", str(tmp_path), "--save", "", "--appendonly", "no"],
        check=True, capture_output=True,
    )
    # health probe runs every 3s; poll until it reconnects (max ~15s)
    deadline = 30
    while deadline and not writer.redis_alive:
        await asyncio.sleep(1)
        deadline -= 1
    await enqueue("after", 5)
    deadline = 20
    while deadline:
        if await _count("run-flap-after") == 5:
            break
        await asyncio.sleep(0.2)
        deadline -= 1

    assert writer.redis_alive is True
    assert await _count("run-flap-after") == 5
    await writer.stop()
    await client.aclose()


async def _count(prefix: str) -> int:
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(
            select(AgentExecutionTrace).where(
                AgentExecutionTrace.run_id.like(f"{prefix}%"))
        )).all()
        return len(rows)


# ------------------------------------------------------- tool failure escalation
async def test_agent_failure_triggers_ticket_and_degraded_report(monkeypatch):
    async def _boom(_tenant_id: int):
        raise RuntimeError("simulated billing database outage")

    monkeypatch.setattr(billing_tools, "fetch_tenant_billing", _boom)
    events = await collect_run("系统报 429 错误了 trc-9f3a2c7b1e4d")

    actions = by_event(events, "agent_action")
    agents_status = {
        e.payload["agent"]: e.payload["status"] for e in actions
    }
    assert agents_status.get("billing") == "error"
    assert "support" in agents_status, "failed expert must escalate to ticket"

    report = by_event(events, "final")[0].payload["report"]
    assert report["tickets"], "ticket must be created"
    assert "降级" in report["conclusion_markdown"]
    assert "billing" in report["conclusion_markdown"]


# ------------------------------------------------------------- restart recovery
async def test_startup_reconciliation_marks_interrupted_runs(uuid_ns):
    async with AsyncSessionLocal() as session:
        session.add(DynamicWorkflowState(
            run_id=f"run-interrupted-{uuid_ns}", trace_id="trc-x",
            current_node="dispatch", round_index=0, max_rounds=2,
            status="dispatched", plan=[], state_snapshot={"goal": "g"},
        ))
        await session.commit()

    marked = await reconcile_interrupted_runs()
    assert marked >= 1
    async with AsyncSessionLocal() as session:
        row = (await session.scalars(
            select(DynamicWorkflowState).where(
                DynamicWorkflowState.run_id == f"run-interrupted-{uuid_ns}")
        )).one()
        assert row.status == "interrupted"


# ---------------------------------------------------------------- hostile input
async def test_oversized_and_empty_messages_rejected():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r1 = await c.post("/api/v1/chat/stream", json={"message": "x" * 5000})
        assert r1.status_code == 422
        r2 = await c.post("/api/v1/chat/stream",
                          json={"message": "\x00\x01\x02   "})
        assert r2.status_code == 422


async def test_control_characters_stripped():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # valid text that merely contains control chars is accepted & cleaned
        r = await c.post(
            "/api/v1/chat/stream",
            json={"message": "429 排查\x00\x07trc-9f3a2c7b1e4d"},
            headers={"X-Gateway-Token": settings.GATEWAY_INTERNAL_TOKEN,
                     "X-Tenant-Id": "1"},
        )
        assert r.status_code == 200
        body = await r.aread()
        assert b"\x00" not in body and b"\x07" not in body


async def test_resume_validates_run_id():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/v1/chat/stream/../../etc/passwd/resume")
        assert r.status_code in (400, 404)
        r2 = await c.get("/api/v1/chat/stream/run-zzzz/resume")
        assert r2.status_code in (400, 404)


async def test_identity_headers_require_gateway_token(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_DEV_PRINCIPAL", False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # spoofed identity header without the shared secret -> forbidden
        r = await c.get("/api/v1/tickets", headers={"X-Tenant-Id": "999"})
        assert r.status_code in (401, 403)
        # correct shared secret -> accepted
        r2 = await c.get(
            "/api/v1/tickets",
            headers={"X-Tenant-Id": "1",
                     "X-Gateway-Token": settings.GATEWAY_INTERNAL_TOKEN},
        )
        assert r2.status_code == 200
    monkeypatch.setattr(settings, "ALLOW_DEV_PRINCIPAL", True)
