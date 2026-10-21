"""Supervisor planning: intent recognition + subtask decomposition.

Two real implementations share one contract:

* ``RulePlanner`` — deterministic weighted signal analysis (regex/TraceID
  extraction/keyword intent lexicon), always available offline;
* ``LLMPlanner`` — structured-output planning with a chat model, falling
  back to the rule engine on any failure (autonomy must never be blocked by
  an unavailable model).
"""

from abc import ABC, abstractmethod

from app.agents.llm import get_llm
from app.agents.schemas import Plan, SubTask
from app.agents.tools.log_tools import extract_trace_id
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_DIAGNOSTIC_LEXICON = (
    "429", "500", "502", "503", "504", "401", "403", "报错", "错误", "异常",
    "故障", "失败", "超时", "timeout", "error", "fail", "5xx", "崩", "挂了",
    "不可用", "拒绝", "trace", "日志", "限流", "突增", "抖动",
)
_BILLING_LEXICON = (
    "429", "配额", "quota", "qps", "限流", "欠费", "余额", "账单", "计费",
    "充值", "发票", "402", "额度", "费用", "扣费", "停服", "套餐", "升配",
)
_KNOWLEDGE_LEXICON = (
    "怎么", "如何", "为什么", "请问", "文档", "手册", "说明", "原因", "怎么办",
    "排查", "解决", "建议", "知识", "doc", "how", "why", "啥是", "什么是",
)


class BasePlanner(ABC):
    @abstractmethod
    async def plan(self, goal: str, history: list[dict[str, str]]) -> Plan: ...


class RulePlanner(BasePlanner):
    """Deterministic decomposition driven by real signal extraction."""

    async def plan(self, goal: str, history: list[dict[str, str]]) -> Plan:
        text = goal.lower()
        trace_id = extract_trace_id(goal)
        signals = self._signals(text)

        subtasks: list[SubTask] = []

        if signals["diagnostic"]:
            subtasks.append(SubTask(
                id="task-diagnostic-1",
                agent="diagnostic",
                goal="定位故障事实：按 TraceID 拉取 API 日志，统计状态码分布、峰值 QPS 与错误原因",
                tool_hint="analyze_trace",
                params={"trace_id": trace_id, "keywords": signals["matched_diag"]},
                reason="目标包含排障信号（错误码/报错/TraceID），需要日志事实",
            ))
        if signals["billing"]:
            subtasks.append(SubTask(
                id="task-billing-1",
                agent="billing",
                goal="核查计费状态：租户 QPS 限制、日配额用量、余额与欠费情况",
                tool_hint="fetch_tenant_billing",
                params={"trace_id": trace_id},
                reason="目标包含计费/限流信号，需要排除配额与欠费触发的流控",
            ))
        if signals["knowledge"] or signals["diagnostic"] or signals["billing"]:
            subtasks.append(SubTask(
                id="task-knowledge-1",
                agent="knowledge",
                goal="检索知识库：混合召回相关排障手册、计费 FAQ 与处理步骤",
                tool_hint="hybrid_knowledge_search",
                params={"query": goal, "trace_id": trace_id},
                reason="诊断与计费处置需要官方手册/FAQ 作为权威依据",
            ))

        if not subtasks:
            subtasks.append(SubTask(
                id="task-knowledge-1",
                agent="knowledge",
                goal="在知识库中检索用户问题的答案",
                tool_hint="hybrid_knowledge_search",
                params={"query": goal},
                reason="未识别到排障/计费信号，按知识问答处理",
            ))

        intent = self._intent(signals, trace_id)
        confidence = min(0.95, 0.45 + 0.12 * len(signals["matched_diag"])
                         + 0.15 * len(signals["matched_bill"])
                         + (0.1 if trace_id else 0.0))
        need_ticket = False
        return Plan(
            intent=intent,
            summary=f"识别意图={intent}，并发派发 {len(subtasks)} 个专家"
                    + (f"，TraceID={trace_id}" if trace_id else ""),
            subtasks=subtasks,
            need_ticket=need_ticket,
            reasoning=(
                f"diagnostic={signals['diagnostic']} "
                f"billing={signals['billing']} knowledge={signals['knowledge']} "
                f"trace_id={trace_id or 'none'}"
            ),
        )

    async def escalation_plan(self, goal: str, verdicts: list[dict]) -> Plan:
        return Plan(
            intent="escalation",
            summary="证据不足或需要人工介入，自动创建工单兜底",
            subtasks=[SubTask(
                id="task-support-1",
                agent="support",
                goal="汇总现有证据，自动创建人工支持工单",
                tool_hint="create_support_ticket",
                params={"verdicts": verdicts},
                reason="知识库未命中或专家建议建单",
            )],
            need_ticket=True,
            reasoning="supervisor review 触发兜底建单",
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _signals(text: str) -> dict:
        matched_diag = sorted({w for w in _DIAGNOSTIC_LEXICON if w in text})
        matched_bill = sorted({w for w in _BILLING_LEXICON if w in text})
        matched_know = sorted({w for w in _KNOWLEDGE_LEXICON if w in text})
        return {
            "diagnostic": bool(matched_diag) or bool(extract_trace_id(text)),
            "billing": bool(matched_bill),
            "knowledge": bool(matched_know),
            "matched_diag": matched_diag,
            "matched_bill": matched_bill,
        }

    @staticmethod
    def _intent(signals: dict, trace_id: str | None) -> str:
        if signals["diagnostic"] and signals["billing"]:
            return "incident_rate_limit"
        if signals["diagnostic"]:
            return "incident_diagnosis"
        if signals["billing"]:
            return "billing_inquiry"
        return "knowledge_qa"


class LLMPlanner(BasePlanner):
    def __init__(self, fallback: RulePlanner) -> None:
        self._fallback = fallback
        self._llm = get_llm()

    async def plan(self, goal: str, history: list[dict[str, str]]) -> Plan:
        import asyncio

        try:
            plan = await asyncio.wait_for(
                self._llm.plan(goal, history),
                timeout=settings.AGENT_LLM_ANALYZE_TIMEOUT_SEC + 10,
            )
            if plan and plan.subtasks:
                trace_id = extract_trace_id(goal)
                for task in plan.subtasks:
                    if task.agent == "diagnostic" and not task.params.get("trace_id"):
                        task.params["trace_id"] = trace_id
                logger.info("LLM plan: intent=%s agents=%s",
                            plan.intent, [s.agent for s in plan.subtasks])
                return plan
        except Exception as exc:
            logger.warning("LLM planning failed, falling back to rules: %s", exc)
        return await self._fallback.plan(goal, history)

    async def escalation_plan(self, goal: str, verdicts: list[dict]) -> Plan:
        return await self._fallback.escalation_plan(goal, verdicts)


def get_planner() -> BasePlanner:
    llm = get_llm()
    if llm.available:
        return LLMPlanner(RulePlanner())
    return RulePlanner()
