"""DiagnosticAgent — diagnostics expert (api_logs / TraceID root-cause analysis)."""

from app.agents.base import BaseAgent
from app.agents.context import RunContext
from app.agents.schemas import AgentVerdict, SubTask
from app.agents.tools import log_tools


class DiagnosticAgent(BaseAgent):
    name = "diagnostic"
    display_name = "排障专家"
    tools = ["extract_trace_id", "analyze_trace", "recent_incidents"]
    system_prompt = (
        "你是 Cots 平台的排障专家（DiagnosticAgent）。你只基于日志系统与 MySQL 中 "
        "api_logs 表的真实数据下结论：按 TraceID 还原调用链，统计状态码分布、峰值 QPS、"
        "错误原因与延迟分位。禁止臆测；证据不足时明确指出并建议建单。"
    )

    async def _work(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        trace_id = task.params.get("trace_id") or log_tools.extract_trace_id(ctx.goal)
        auto_discovered = False

        if not trace_id:
            incidents = await self.call_tool(
                ctx, "recent_incidents",
                log_tools.recent_incidents(ctx.identity.tenant_id),
                task.id,
            )
            if incidents:
                trace_id = incidents[0]["trace_id"]
                auto_discovered = True

        if not trace_id:
            return AgentVerdict(
                agent=self.name, status="empty",
                summary="未提供 TraceID，且近 60 分钟无错误日志可关联",
                evidences=[self.evidence(
                    "diag-no-trace", "log", "日志检索为空",
                    "api_logs 中没有可用于排障的错误记录",
                    source="mysql:api_logs", status="empty", payload={},
                )],
                requests_ticket=True, confidence=0.2,
            )

        analysis = await self.call_tool(
            ctx, "analyze_trace",
            log_tools.analyze_trace(trace_id),
            task.id,
        )

        if not analysis.get("found"):
            return AgentVerdict(
                agent=self.name, status="empty",
                summary=f"TraceID {trace_id} 在 api_logs 中无记录",
                evidences=[self.evidence(
                    f"diag-{trace_id}-empty", "log", "TraceID 无记录",
                    f"日志系统未检索到 {trace_id}", source="mysql:api_logs",
                    status="empty", payload=analysis,
                )],
                requests_ticket=True, confidence=0.25,
            )

        root_causes = log_tools.derive_root_causes(analysis)
        verdict_summary = self._rule_summary(analysis, trace_id, auto_discovered)

        llm = await self.llm_analyze(ctx, ctx.goal, analysis)
        if llm is not None:
            verdict_summary = llm.summary
            if llm.root_causes:
                root_causes = list(dict.fromkeys(llm.root_causes + root_causes))

        return AgentVerdict(
            agent=self.name, status="ok", summary=verdict_summary,
            evidences=[self.evidence(
                f"diag-{trace_id}", "log",
                f"TraceID {trace_id} 日志分析（{analysis['total']} 条请求）",
                verdict_summary,
                source="mysql:api_logs",
                payload={"analysis": analysis, "root_causes": root_causes,
                         "auto_discovered": auto_discovered},
            )],
            confidence=min(0.95, 0.5 + analysis["error_rate"]),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _rule_summary(analysis: dict, trace_id: str, auto: bool) -> str:
        prefix = "（未提供 TraceID，已自动关联最近事故）\n" if auto else ""
        errors = analysis["error_count"]
        return (
            f"{prefix}TraceID {trace_id} 共 {analysis['total']} 条请求，错误 {errors} 条 "
            f"（错误率 {analysis['error_rate']:.0%}），状态码分布 "
            f"{analysis['status_breakdown']}，峰值 {analysis['peak_qps']} QPS。"
        )
