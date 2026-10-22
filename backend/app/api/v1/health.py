"""Health/readiness with real dependency probes."""

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.retrieval.service import HybridRetrievalService
from app.services.container import container
from app.services.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    checks: dict[str, dict] = {}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["mysql"] = {"ok": True}
    except Exception as exc:
        checks["mysql"] = {"ok": False, "error": str(exc)}

    try:
        redis_client = get_redis()
        await redis_client.ping()
        checks["redis"] = {"ok": True}
    except Exception as exc:
        checks["redis"] = {"ok": False, "error": str(exc)}

    try:
        service = HybridRetrievalService.instance()
        from app.retrieval.vector_store import get_vector_store

        milvus = get_vector_store()
        ok = milvus.healthy()
        checks["milvus"] = {
            "ok": ok,
            "rows": milvus.count() if ok else 0,
            "bm25_ready": service.ready,
        }
    except Exception as exc:
        checks["milvus"] = {"ok": False, "error": str(exc)}

    checks["trace_writer"] = {
        "ok": True,
        "redis_alive": container.trace_writer.redis_alive,
        **container.trace_writer.stats,
    }
    healthy = all(item.get("ok") for item in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
