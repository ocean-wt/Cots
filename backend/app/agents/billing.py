"""BillingAgent — billing expert (quota / QPS / arrears from the billing tables)."""

from app.agents.base import BaseAgent
from app.agents.context import RunContext
from app.agents.schemas import AgentVerdict, SubTask
from app.agents.tools import billing_tools


class BillingAgent(BaseAgent):
    name = "billing"
    display_name = "账单专家"
    tools = ["fetch_tenant_billing"]
    system_prompt = (
        "你是 Cots 平台的账单专家（BillingAgent）。你连接计费系统，核查租户套餐 QPS 限制、"
        "日配额用量、账户余额与欠费状态。你必须基于 tenants 表的真实字段回答，"
        "并明确区分瞬时限流（RATE_LIMITED）、配额耗尽（QUOTA_EXHAUSTED）与欠费停服。"
    )

    async def _work(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        billing = await self.call_tool(
            ctx, "fetch_tenant_billing",
            billing_tools.fetch_tenant_billing(ctx.identity.tenant_id),
            task.id,
        )
        if billing is None:
            return AgentVerdict(
                agent=self.name, status="error",
                summary=f"租户 {ctx.identity.tenant_id} 不存在，无法核查账单",
                evidences=[self.evidence(
                    "billing-missing", "billing", "租户不存在",
                    "计费系统未找到该租户", source="mysql:tenants",
                    status="error", payload={"tenant_id": ctx.identity.tenant_id},
                )],
                confidence=0.1,
            )

        findings = self._findings(billing)
        summary = self._rule_summary(billing, findings)
        llm = await self.llm_analyze(ctx, ctx.goal, {"billing": billing})
        if llm is not None:
            summary = llm.summary

        return AgentVerdict(
            agent=self.name, status="ok", summary=summary,
            evidences=[self.evidence(
                f"billing-tenant-{billing['tenant_id']}", "billing",
                f"{billing['name']} 账单与配额状态",
                summary, source="mysql:tenants",
                payload={"billing": billing, "findings": findings},
            )],
            confidence=0.9 if findings else 0.6,
        )

    @staticmethod
    def _findings(billing: dict) -> list[str]:
        findings: list[str] = []
        if billing["quota_exhausted"]:
            findings.append(
                f"日配额已耗尽：已用 {billing['used_today']:,} / "
                f"{billing['daily_quota']:,}（{billing['quota_usage_ratio']:.0%}）"
            )
        if billing["overdue"]:
            findings.append(
                f"账户欠费 {abs(billing['balance_yuan'])} {billing['currency']}，"
                f"逾期 {billing['overdue_days']} 天，写接口被强制限流"
            )
        findings.append(
            f"套餐 {billing['plan']} 的 QPS 上限为 {billing['qps_limit']}"
        )
        return findings

    @staticmethod
    def _rule_summary(billing: dict, findings: list[str]) -> str:
        flags: list[str] = []
        if billing["quota_exhausted"]:
            flags.append("配额耗尽")
        if billing["overdue"]:
            flags.append("欠费停服中")
        state = "、".join(flags) if flags else "账单状态正常"
        return (
            f"租户 {billing['tenant_code']}（{billing['plan']} 套餐）：{state}；"
            + "；".join(findings)
        )
