"""KnowledgeAgent — knowledge expert (Milvus dense + BM25 sparse hybrid RAG)."""

from app.agents.base import BaseAgent
from app.agents.context import RunContext
from app.agents.schemas import AgentVerdict, SubTask
from app.agents.tools import knowledge_tools


class KnowledgeAgent(BaseAgent):
    name = "knowledge"
    display_name = "知识专家"
    tools = ["hybrid_knowledge_search"]
    system_prompt = (
        "你是 Cots 平台的知识专家（KnowledgeAgent）。你连接 Milvus 向量库与 BM25 全文索引，"
        "执行双路 Top20 召回、RRF 融合与 gte-rerank 精排。命中时给出文档证据与可执行步骤；"
        "精排分数低于阈值时必须如实返回 hit=False 并请求 Supervisor 转人工建单兜底。"
    )

    async def _work(self, ctx: RunContext, task: SubTask) -> AgentVerdict:
        query = task.params.get("query") or ctx.goal
        result = await self.call_tool(
            ctx, "hybrid_knowledge_search",
            knowledge_tools.hybrid_knowledge_search(query),
            task.id,
        )

        if not result["hit"]:
            return AgentVerdict(
                agent=self.name, status="empty",
                summary=f"知识库未命中可信答案（{result['reason']}），建议建单兜底",
                evidences=[self.evidence(
                    "knowledge-miss", "knowledge", "混合检索未命中",
                    result["reason"], source="milvus+bm25", status="empty",
                    payload=result,
                )],
                requests_ticket=True, confidence=0.15,
            )

        top_chunks = result["chunks"][:4]
        docs = "、".join(sorted({c["doc_title"] for c in top_chunks}))
        best_score = top_chunks[0]["scores"]["rerank"]
        summary = (
            f"混合检索命中 {result['total_candidates']} 个候选，"
            f"最高精排分 {best_score:.3f}，权威文档：{docs}"
        )

        llm = await self.llm_analyze(ctx, query, {"retrieval": result})
        if llm is not None:
            summary = llm.summary

        return AgentVerdict(
            agent=self.name, status="ok", summary=summary,
            evidences=[self.evidence(
                "knowledge-hit", "knowledge",
                f"知识库命中：{docs}", summary,
                source="milvus+bm25(rrf+rerank)",
                payload=result,
            )],
            requests_ticket=False, confidence=float(best_score),
        )
