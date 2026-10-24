"""Concurrent fan-out and anti-deadlock behaviour of the supervisor graph."""

import asyncio

import pytest

from app.agents.context import Identity
from tests.helpers import actions_by_agent, by_event, collect_run

pytestmark = pytest.mark.usefixtures("stack")

GOAL_429 = "系统报 429 错误了，traceID trc-9f3a2c7b1e4d，帮我紧急排查"


async def test_three_experts_dispatched_and_concluded():
    events = await collect_run(GOAL_429, Identity())

    actions = actions_by_agent(events)
    assert {"diagnostic", "billing", "knowledge"} <= set(actions)
    for agent_name in ("diagnostic", "billing", "knowledge"):
        statuses = [e.payload["status"] for e in actions[agent_name]]
        assert "running" in statuses and "done" in statuses

    # Concurrent dispatch: every expert must START before any of them ends.
    running_seqs = [
        e.seq for e in by_event(events, "agent_action")
        if e.payload["status"] == "running" and e.payload["agent"] != "supervisor"
    ]
    done_seqs = [
        e.seq for e in by_event(events, "agent_action")
        if e.payload["status"] in {"done", "error", "timeout"}
        and e.payload["agent"] != "supervisor"
    ]
    assert len(running_seqs) >= 3
    assert min(done_seqs) > max(running_seqs), "experts did not run concurrently"

    # Evidence chain contains all three real evidence kinds
    evidence_kinds = {e.payload["kind"] for e in by_event(events, "evidence")}
    assert {"log", "billing", "knowledge"} <= evidence_kinds

    finals = by_event(events, "final")
    assert len(finals) == 1
    report = finals[0].payload["report"]
    assert "trc-9f3a2c7b1e4d" in report["conclusion_markdown"]
    assert report["root_causes"], "root causes must be derived from evidence"
    assert report["steps"], "remediation steps must be present"
    assert report["rounds"] <= 2
    assert by_event(events, "done") and not by_event(events, "error")


async def test_diagnostic_finds_real_429_burst():
    events = await collect_run(GOAL_429)
    log_evidence = next(
        e for e in by_event(events, "evidence") if e.payload["kind"] == "log"
    )
    analysis = log_evidence.payload["payload"]["analysis"]
    assert analysis["found"] is True
    assert analysis["status_breakdown"].get(429, 0) >= 10
    assert analysis["peak_qps"] >= 1
    assert analysis["error_rate"] > 0.5


async def test_max_rounds_prevents_deadlock_and_falls_back_to_ticket():
    # Out-of-vocabulary goal: dense + sparse retrieval both miss → ticket.
    events = await collect_run("龘靐齉齾爩灪厵 plokijuhygt qazwsxedcr")

    rounds = by_event(events, "round")
    assert len(rounds) == 2, f"expected plan + one escalation round, got {len(rounds)}"
    assert {t["agent"] for t in rounds[1].payload["plan"]} == {"support"}

    actions = actions_by_agent(events)
    assert "support" in actions

    report = by_event(events, "final")[0].payload["report"]
    assert len(report["tickets"]) == 1
    ticket_no = report["tickets"][0]["ticket_no"]
    assert ticket_no.startswith("TKT-")

    # supervisor always terminates within the hard round cap
    assert by_event(events, "done")
    assert report["rounds"] == 2
