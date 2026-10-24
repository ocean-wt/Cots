"""Knowledge administration: index stats, rebuild and direct retrieval."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import Principal, get_principal
from app.db.models import KnowledgeChunk
from app.db.session import AsyncSessionLocal
from app.retrieval.service import HybridRetrievalService

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 20


@router.get("/knowledge/stats")
async def knowledge_stats(_: Principal = Depends(get_principal)) -> dict:
    async with AsyncSessionLocal() as session:
        total = await session.scalar(
            select(func.count()).select_from(KnowledgeChunk)
        )
        docs = (
            await session.scalars(
                select(KnowledgeChunk.doc_id).distinct()
            )
        ).all()
    try:
        from app.retrieval.vector_store import get_vector_store

        vectors = get_vector_store().count()
    except Exception:
        vectors = 0
    service = HybridRetrievalService.instance()
    return {
        "chunks": total,
        "documents": sorted(set(docs)),
        "bm25_indexed": service._bm25.size if hasattr(service, "_bm25") else 0,
        "milvus_vectors": vectors,
        "ready": service.ready,
    }


@router.post("/knowledge/rebuild")
async def rebuild_index(_: Principal = Depends(get_principal)) -> dict:
    result = await HybridRetrievalService.instance().rebuild()
    return {"status": "ok", **result}


@router.post("/knowledge/search")
async def direct_search(
    body: SearchRequest, _: Principal = Depends(get_principal)
) -> dict:
    result = await HybridRetrievalService.instance().retrieve(
        body.query, top_k=body.top_k
    )
    return {
        "hit": result.hit,
        "reason": result.reason,
        "total_candidates": result.total_candidates,
        "chunks": [c.to_evidence_payload() for c in result.chunks],
    }
