"""SupportAgent — ticketing expert (escalation fallback into the tickets table)."""

from app.agents.base import BaseAgent
from app.agents.context import RunContext
from app.agents.schemas import AgentVerdict, SubTask
from app.agents.tools import ticket_tools


class SupportAgent(BaseAgent):
    name = "support"
    display_name = "建单专家"
    tools = ["create_support_ticket"]
    system_prompt = (
        "你是 Cots 平台的建单专家（SupportAgent）。当知识未命中或问题需要人工介入时，"
        "你汇总各专家收集的证据（日志、账单、检索结果），在 tickets 表创建结构化工单，"
        "设置合理优先级并保证 TraceID 与证据链完整可追溯。"
    )

    async def _work(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        verdicts = task.params.get("verdicts") or []
        priority = self._priority(verdicts)
        title = f"[智能建单] {ctx.goal[:60]}"
        detail = {
            "goal": ctx.goal,
            "run_id": ctx.run_id,
            "agent_verdicts": verdicts,
        }
        ticket = await self.call_tool(
            ctx, "create_support_ticket",
            ticket_tools.create_support_ticket(
                tenant_id=ctx.identity.tenant_id,
                title=title,
                detail=detail,
                trace_id=ctx.trace_id,
                priority=priority,
            ),
            task.id,
        )
        return AgentVerdict(
            agent=self.name, status="ok",
            summary=f"已创建工单 {ticket['ticket_no']}（{priority}），人工专家将跟进处理",
            evidences=[self.evidence(
                f"ticket-{ticket['ticket_no']}", "ticket",
                f"工单 {ticket['ticket_no']}",
                f"Supervisor 兜底建单，优先级 {priority}，关联 TraceID {ctx.trace_id}",
                source="mysql:tickets", payload=ticket,
            )],
            confidence=0.99,
        )

    @staticmethod
    def _priority(verdicts: list[dict]) -> str:
        agents = {v.get("agent") for v in verdicts}
        has_overdue = any(
            ("欠费" in v.get("summary", "") or "overdue" in v.get("summary", "").lower())
            for v in verdicts if v.get("agent") == "billing"
        )
        if has_overdue or {"diagnostic", "billing"} <= agents:
            return "P1"
        return "P2"
