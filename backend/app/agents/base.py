"""Base contract for every specialized agent."""

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.agents.context import RunContext, StepTimer
from app.agents.llm import AgentAnalysis, get_llm
from app.agents.schemas import AgentVerdict, Evidence, SubTask
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    name: str = "agent"
    display_name: str = "专家智能体"
    system_prompt: str = ""
    tools: list[str] = []

    @abstractmethod
    async def _work(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        ...

    async def execute(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        timer = StepTimer()
        tokens_before = (ctx.tokens.prompt, ctx.tokens.completion)
        await ctx.agent_action(
            self.name, "running", task.goal,
            detail=task.reason, task_id=task.id, tools=self.tools,
        )
        try:
            verdict = await asyncio.wait_for(
                self._work(ctx, task),
                timeout=settings.AGENT_NODE_TIMEOUT_SEC,
            )
            verdict.duration_ms = timer.elapsed_ms()
        except TimeoutError:
            logger.error("agent %s timed out after %ss",
                         self.name, settings.AGENT_NODE_TIMEOUT_SEC)
            verdict = AgentVerdict(
                agent=self.name,
                status="timeout",
                summary=f"{self.display_name}执行超时，已触发熔断兜底",
                error=f"timeout after {settings.AGENT_NODE_TIMEOUT_SEC}s",
                duration_ms=timer.elapsed_ms(),
            )
        except Exception as exc:  # one agent failing must never kill the run
            logger.exception("agent %s failed: %s", self.name, exc)
            verdict = AgentVerdict(
                agent=self.name, status="error",
                summary=f"{self.display_name}执行异常：{exc}",
                error=str(exc), duration_ms=timer.elapsed_ms(),
            )

        end_status = {"ok": "done", "empty": "done", "error": "error",
                      "timeout": "timeout"}.get(verdict.status, "done")
        await ctx.agent_action(
            self.name, end_status, verdict.summary,
            detail=f"耗时 {verdict.duration_ms}ms", task_id=task.id,
        )
        for evidence in verdict.evidences:
            await ctx.emit("evidence", **evidence.model_dump())
        ctx.tokens.add(
            prompt=verdict.token_usage.get("prompt_tokens", 0),
            completion=verdict.token_usage.get("completion_tokens", 0),
        )
        # Persist this agent's token delta asynchronously (lossless queue).
        delta_prompt = max(0, ctx.tokens.prompt - tokens_before[0])
        delta_completion = max(0, ctx.tokens.completion - tokens_before[1])
        await ctx.trace(
            agent=self.name, node=self.name, phase="end",
            action=verdict.summary[:240], task_id=task.id,
            status=verdict.status, duration_ms=verdict.duration_ms,
            token_usage={
                "prompt_tokens": delta_prompt,
                "completion_tokens": delta_completion,
                "total_tokens": delta_prompt + delta_completion,
            },
        )
        return verdict

    async def call_tool(
        self, ctx: RunContext, tool_name: str, coro_factory, task_id: str | None = None
    ) -> Any:
        """Execute a bound tool, streaming its lifecycle to the UI/trace log."""
        await ctx.agent_action(
            self.name, "running", f"调用工具 {tool_name}",
            detail=f"系统提示词角色：{self.display_name}", task_id=task_id,
        )
        await ctx.trace(
            agent=self.name, node=self.name, phase="tool_call",
            action=tool_name, task_id=task_id,
        )
        result = await coro_factory
        await ctx.trace(
            agent=self.name, node=self.name, phase="tool_result",
            action=tool_name, task_id=task_id,
            output_payload={"preview": str(result)[:800]},
        )
        return result

    async def llm_analyze(
        self, ctx: RunContext, goal: str, tool_output: dict
    ) -> AgentAnalysis | None:
        llm = get_llm()
        if not llm.available:
            return None
        try:
            analysis, usage = await asyncio.wait_for(
                llm.analyze(self.name, self.system_prompt, goal, tool_output),
                timeout=settings.AGENT_LLM_ANALYZE_TIMEOUT_SEC,
            )
        except TimeoutError:
            logger.warning(
                "LLM analyze timed out for %s after %ss — keeping rule summary "
                "and tool evidence",
                self.name, settings.AGENT_LLM_ANALYZE_TIMEOUT_SEC,
            )
            return None
        except Exception as exc:
            logger.warning("LLM analyze failed for %s (%s) — rule fallback",
                           self.name, exc)
            return None
        ctx.tokens.add(
            prompt=usage.get("prompt_tokens", 0),
            completion=usage.get("completion_tokens", 0),
        )
        return analysis

    def evidence(
        self,
        evidence_id: str,
        kind: str,
        title: str,
        summary: str,
        source: str,
        payload: dict[str, Any],
        status: str = "ok",
    ) -> Evidence:
        return Evidence(
            id=f"{evidence_id}-{uuid.uuid4().hex[:8]}", kind=kind, title=title,
            summary=summary,
            source=source, agent=self.name, status=status, payload=payload,
        )
