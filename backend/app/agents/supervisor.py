"""LangGraph nodes implementing the supervisor collaboration pattern."""

import asyncio
import time

from langchain_core.runnables.config import RunnableConfig
from app.agents.billing import BillingAgent
from app.agents.diagnostic import DiagnosticAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.planner import RulePlanner, get_planner
from app.agents.runtime_ctx import get_run_ctx
from app.agents.state import CotsState
from app.agents.support import SupportAgent
from app.agents.synthesizer import synthesize_and_stream
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Message
from app.db.session import AsyncSessionLocal
from app.services.workflow_state import upsert_workflow_state

logger = get_logger(__name__)

AGENT_REGISTRY = {
    "diagnostic": DiagnosticAgent(),
    "billing": BillingAgent(),
    "knowledge": KnowledgeAgent(),
    "support": SupportAgent(),
}


# --------------------------------------------------------------------------- #
# Node 1: supervisor — intent recognition + task decomposition
# --------------------------------------------------------------------------- #
async def supervisor_node(state: CotsState, config: RunnableConfig) -> dict:
    ctx = get_run_ctx(config)
    goal = state["goal"]
    history = state.get("history", [])

    await ctx.agent_action(
        "supervisor", "planning",
        "Supervisor 正在理解目标并拆解任务",
        detail=goal[:120],
    )
    await ctx.trace(agent="supervisor", node="supervisor", phase="start",
                    action="plan", input_payload={"goal": goal})

    planner = get_planner()
    started = time.perf_counter()
    plan = await planner.plan(goal, history)
    elapsed = int((time.perf_counter() - started) * 1000)

    await ctx.agent_action(
        "supervisor", "planning",
        f"Supervisor 已拆解为 {len(plan.subtasks)} 个并发子任务",
        detail=plan.summary,
    )
    await ctx.emit(
        "round",
        round=state.get("round", 0),
        max_rounds=state.get("max_rounds", settings.AGENT_MAX_ROUNDS),
        intent=plan.intent,
        plan=[task.model_dump() for task in plan.subtasks],
    )
    await ctx.trace(
        agent="supervisor", node="supervisor", phase="end", action="plan",
        detail=plan.summary, duration_ms=elapsed,
        output_payload={"plan": plan.model_dump()},
    )
    await upsert_workflow_state(
        run_id=ctx.run_id, trace_id=ctx.trace_id,
        current_node="dispatch", round_index=state.get("round", 0),
        max_rounds=state.get("max_rounds", settings.AGENT_MAX_ROUNDS),
        status="planned", plan=[t.model_dump() for t in plan.subtasks],
        snapshot={
            "goal": goal,
            "intent": plan.intent,
            "trace_id": ctx.trace_id,
            "conversation_id": state.get("conversation_id"),
        },
    )
    return {"intent": plan.intent, "plan": plan.model_dump()}


# --------------------------------------------------------------------------- #
# Node 2: concurrent expert fan-out
# --------------------------------------------------------------------------- #
async def dispatch_node(state: CotsState, config: RunnableConfig) -> dict:
    ctx = get_run_ctx(config)
    subtasks = state["plan"]["subtasks"]
    ctx.round_index = state.get("round", 0)

    await ctx.agent_action(
        "supervisor", "dispatching",
        f"并发派发给 {len(subtasks)} 个专业智能体",
        detail=" → ".join(AGENT_REGISTRY[t["agent"]].display_name
                          for t in subtasks if t["agent"] in AGENT_REGISTRY),
    )

    prior_verdicts = state.get("verdicts", [])

    async def _run(task: dict):
        agent = AGENT_REGISTRY.get(task["agent"])
        if agent is None:
            return None
        # late-bind prior verdicts so the escalation (SupportAgent) gets them
        if task["agent"] == "support" and not task.get("params", {}).get("verdicts"):
            task.setdefault("params", {})["verdicts"] = prior_verdicts
        from app.agents.schemas import SubTask

        return await agent.execute(ctx, SubTask.model_validate(task))

    results = await asyncio.gather(*[_run(t) for t in subtasks])

    verdicts: list[dict] = []
    evidences: list[dict] = []
    tickets: list[dict] = []
    for result in results:
        if result is None:
            continue
        verdict_dict = result.model_dump()
        verdicts.append(verdict_dict)
        evidences.extend(verdict_dict["evidences"])
        for ev in verdict_dict["evidences"]:
            if ev["kind"] == "ticket":
                tickets.append(ev["payload"])

    await upsert_workflow_state(
        run_id=ctx.run_id, trace_id=ctx.trace_id,
        current_node="review", round_index=ctx.round_index,
        max_rounds=state.get("max_rounds", settings.AGENT_MAX_ROUNDS),
        status="dispatched", plan=subtasks,
        snapshot={
            "goal": state["goal"],
            "trace_id": ctx.trace_id,
            "conversation_id": state.get("conversation_id"),
        },
        verdict_summary={"verdicts": verdicts, "tickets": tickets},
    )
    return {"verdicts": verdicts, "evidences": evidences, "tickets": tickets}


# --------------------------------------------------------------------------- #
# Node 3: review — decide whether another bounded round (ticket fallback) runs
# --------------------------------------------------------------------------- #
async def review_node(state: CotsState, config: RunnableConfig) -> dict:
    ctx = get_run_ctx(config)
    current_round = state.get("round", 0)
    max_rounds = state.get("max_rounds", settings.AGENT_MAX_ROUNDS)
    verdicts = state.get("verdicts", [])

    needs_ticket = any(v.get("requests_ticket") for v in verdicts)
    # Predictable failure handling: a failed/timed-out expert must not be
    # silently presented as answered — escalate to human follow-up too.
    failed = [
        v.get("agent") for v in verdicts
        if v.get("status") in ("error", "timeout")
    ]
    needs_ticket = needs_ticket or bool(failed)
    already_created = any(v.get("agent") == "support" for v in verdicts)
    can_continue = current_round + 1 < max_rounds

    if needs_ticket and can_continue and not already_created:
        planner = RulePlanner()
        escalation = await planner.escalation_plan(state["goal"], verdicts)
        ctx.round_index = current_round + 1
        reason_text = (
            f"证据不足或专家失败（{', '.join(failed)}），转入建单兜底流程"
            if failed else "知识库未命中/证据不足，转入建单兜底流程"
        )
        await ctx.agent_action(
            "supervisor", "planning", reason_text,
            detail=escalation.summary,
        )
        await ctx.emit(
            "round",
            round=current_round + 1,
            max_rounds=max_rounds,
            intent=escalation.intent,
            plan=[t.model_dump() for t in escalation.subtasks],
        )
        return {
            "round": current_round + 1,
            "plan": escalation.model_dump(),
        }
    return {}


def route_after_review(state: CotsState) -> str:
    plan = state.get("plan") or {}
    subtasks = plan.get("subtasks") or []
    already_supported = any(
        v.get("agent") == "support" for v in state.get("verdicts", [])
    )
    if (
        subtasks
        and subtasks[0].get("agent") == "support"
        and not already_supported
    ):
        return "dispatch"
    return "synthesize"


# --------------------------------------------------------------------------- #
# Node 4: synthesize the final evidence-chain report
# --------------------------------------------------------------------------- #
async def synthesize_node(state: CotsState, config: RunnableConfig) -> dict:
    ctx = get_run_ctx(config)
    ctx.round_index = state.get("round", 0)
    await ctx.agent_action(
        "supervisor", "synthesizing",
        "Supervisor 正在汇总证据链并生成最终结论",
    )

    report = await synthesize_and_stream(
        ctx=ctx,
        goal=state["goal"],
        intent=state.get("intent", "unknown"),
        verdicts=state.get("verdicts", []),
        evidences=state.get("evidences", []),
        round_index=state.get("round", 0),
    )

    conversation_id = state.get("conversation_id") or ctx.conversation_id
    if conversation_id:
        async with AsyncSessionLocal() as session:
            session.add(Message(
                conversation_id=conversation_id,
                role="assistant",
                content=report.conclusion_markdown,
                trace_id=ctx.trace_id,
                token_usage=report.token_usage,
                structured=report.model_dump(mode="json"),
            ))
            await session.commit()

    await upsert_workflow_state(
        run_id=ctx.run_id, trace_id=ctx.trace_id,
        current_node="done", round_index=state.get("round", 0),
        max_rounds=state.get("max_rounds", settings.AGENT_MAX_ROUNDS),
        status="completed", plan=(state.get("plan") or {}).get("subtasks", []),
        snapshot={
            "goal": state["goal"],
            "trace_id": ctx.trace_id,
            "conversation_id": conversation_id,
        },
        verdict_summary={"confidence": report.confidence},
    )
    await ctx.agent_action("supervisor", "done", "任务完成")
    return {"final": report.model_dump(mode="json")}
