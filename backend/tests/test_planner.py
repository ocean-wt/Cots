"""Supervisor intent recognition + task decomposition tests."""

import pytest

from app.agents.planner import RulePlanner

pytestmark = pytest.mark.usefixtures("stack")


@pytest.mark.parametrize(
    "goal,expected_agents,intent_part",
    [
        ("系统报 429 错误了，traceID trc-9f3a2c7b1e4d",
         {"diagnostic", "billing", "knowledge"}, "rate_limit"),
        ("我们租户是不是欠费了？QPS 被限制", {"billing", "knowledge"}, "billing"),
        ("这个接口 500，trc-9f3a2c7b1e4d 帮我看看", {"diagnostic", "knowledge"},
         "diagnosis"),
        ("请问如何配置 webhook 回调？", {"knowledge"}, "knowledge_qa"),
    ],
)
async def test_decomposition(goal, expected_agents, intent_part):
    planner = RulePlanner()
    plan = await planner.plan(goal, history=[])

    agents = {t.agent for t in plan.subtasks}
    assert expected_agents <= agents
    assert intent_part in plan.intent
    assert all(t.goal and t.tool_hint for t in plan.subtasks)
    if "trc-" in goal:
        diag = next(t for t in plan.subtasks if t.agent == "diagnostic")
        assert diag.params["trace_id"] == "trc-9f3a2c7b1e4d"


async def test_unknown_goal_still_routes_somewhere():
    plan = await RulePlanner().plan("随便聊聊今天天气", history=[])
    assert plan.subtasks, "planner must always produce at least one subtask"
    assert plan.subtasks[0].agent == "knowledge"


async def test_escalation_plan_creates_support_task():
    plan = await RulePlanner().escalation_plan("查不到", verdicts=[])
    assert plan.need_ticket is True
    assert plan.subtasks[0].agent == "support"
    assert plan.subtasks[0].tool_hint == "create_support_ticket"
