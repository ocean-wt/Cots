"""KnowledgeAgent toolset — hybrid Milvus + BM25 retrieval with RRF/rerank."""

from app.retrieval.service import HybridRetrievalService


async def hybrid_knowledge_search(query: str, top_k: int = 20) -> dict:
    service = HybridRetrievalService.instance()
    result = await service.retrieve(query, top_k=top_k)
    return {
        "query": result.query,
        "hit": result.hit,
        "reason": result.reason,
        "total_candidates": result.total_candidates,
        "chunks": [c.to_evidence_payload() for c in result.chunks],
    }
