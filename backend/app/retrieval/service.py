"""Hybrid retrieval orchestration: dense (Milvus) + BM25 -> RRF -> gte rerank."""

import asyncio
import threading

import numpy as np
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import KnowledgeChunk
from app.db.session import AsyncSessionLocal
from app.retrieval.bm25 import BM25Index
from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.rerank import is_confident, simulate_gte_rerank
from app.retrieval.schema import IndexedChunk, RetrievedChunk, RetrievalResult
from app.retrieval.vector_store import get_vector_store

logger = get_logger(__name__)


class HybridRetrievalService:
    """Process-wide singleton holding the BM25 index and chunk metadata."""

    _instance: "HybridRetrievalService | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._bm25 = BM25Index()
        self._chunks: dict[str, IndexedChunk] = {}
        self._ready = False
        self._rebuild_lock = asyncio.Lock()
        self._rebuild_task: asyncio.Task | None = None

    @classmethod
    def instance(cls) -> "HybridRetrievalService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------ #
    async def rebuild(self) -> dict[str, int]:
        """Rebuild BM25 + Milvus index.

        Concurrent callers coalesce onto one in-flight rebuild so a thundering
        herd (startup + API rebuild calls) cannot double-write vectors.
        """
        if self._rebuild_task is not None and not self._rebuild_task.done():
            return await self._rebuild_task
        async with self._rebuild_lock:
            if self._rebuild_task is not None and not self._rebuild_task.done():
                return await self._rebuild_task
            self._rebuild_task = asyncio.create_task(self._rebuild())
            try:
                return await self._rebuild_task
            finally:
                self._rebuild_task = None

    async def _rebuild(self) -> dict[str, int]:
        """Load chunks from MySQL, embed into Milvus, (re)fit BM25."""
        async with AsyncSessionLocal() as session:
            rows = (await session.scalars(select(KnowledgeChunk))).all()
            if not rows:
                self._chunks = {}
                self._bm25.fit([])
                self._ready = True
                return {"chunks": 0, "vectors": 0}

            chunks = [
                IndexedChunk(
                    chunk_uid=r.chunk_uid,
                    doc_id=r.doc_id,
                    doc_title=r.doc_title,
                    section=r.section,
                    tags=list(r.tags or []),
                    content=r.content,
                    embedding=None,
                    rerank_bias=r.rerank_bias or 0.0,
                )
                for r in rows
            ]

        # ---- dense channel: real embedding model + Milvus --------------
        embedder_task = asyncio.to_thread(_load_embedder_safe)
        store = get_vector_store()
        embedder = await embedder_task
        texts = [f"{c.doc_title} {c.section}\n{c.content}" for c in chunks]
        vectors = await asyncio.to_thread(embedder.encode, texts, False, 16)
        inserted = await asyncio.to_thread(
            store.upsert_chunks,
            [c.chunk_uid for c in chunks],
            [c.doc_id for c in chunks],
            [c.doc_title for c in chunks],
            [c.section for c in chunks],
            [c.content for c in chunks],
            [v.tolist() for v in vectors],
        )
        for chunk, vec in zip(chunks, vectors, strict=True):
            chunk.embedding = vec
        await self._mark_indexed([c.chunk_uid for c in chunks])
        await self._prune_vectors({c.chunk_uid for c in chunks})

        # ---- sparse channel: hand-written BM25 --------------------------
        await asyncio.to_thread(self._bm25.fit, chunks)
        self._chunks = {c.chunk_uid: c for c in chunks}
        self._ready = True
        logger.info("retrieval index rebuilt chunks=%d vectors=%d", len(chunks), inserted)
        return {"chunks": len(chunks), "vectors": inserted}

    async def _mark_indexed(self, uids: list[str]) -> None:
        async with AsyncSessionLocal() as session:
            rows = (await session.scalars(select(KnowledgeChunk))).all()
            by_uid = {r.chunk_uid: r for r in rows}
            for uid in uids:
                if uid in by_uid:
                    by_uid[uid].embedding_status = "indexed"
            await session.commit()

    async def _prune_vectors(self, live_uids: set[str]) -> None:
        def _prune() -> int:
            store = get_vector_store()
            stale = store.all_chunk_uids() - live_uids
            if stale:
                quoted = ", ".join(f'"{u}"' for u in stale)
                store.client.delete(store.collection, filter=f"chunk_uid in [{quoted}]")
            return len(stale)

        removed = await asyncio.to_thread(_prune)
        if removed:
            logger.info("pruned %d stale vectors", removed)

    # ------------------------------------------------------------------ #
    async def retrieve(self, query: str, top_k: int | None = None) -> RetrievalResult:
        if not self._ready:
            await self.rebuild()
        top_k = top_k or settings.RETRIEVAL_TOP_K

        from app.retrieval.embeddings import get_embedder

        embedder = get_embedder()
        store = get_vector_store()
        qvec = (await asyncio.to_thread(embedder.encode, [query], True))[0]

        bm25_task = asyncio.to_thread(self._bm25.search, query, top_k)
        dense_task = asyncio.to_thread(store.search, qvec.tolist(), top_k)
        bm25_hits, dense_rows = await asyncio.gather(bm25_task, dense_task)
        dense_hits = [(uid, score) for uid, score, _entity in dense_rows]

        candidates_map: dict[str, RetrievedChunk] = {}
        for uid, _dense_score, entity in dense_rows:
            meta = self._chunks.get(uid)
            candidates_map[uid] = RetrievedChunk(
                chunk_uid=uid,
                doc_id=entity.get("doc_id") or (meta.doc_id if meta else uid),
                doc_title=entity.get("doc_title") or (meta.doc_title if meta else ""),
                section=entity.get("section") or (meta.section if meta else ""),
                tags=meta.tags if meta else [],
                content=entity.get("text") or (meta.content if meta else ""),
                rerank_bias=meta.rerank_bias if meta else 0.0,
            )
        for uid, _ in bm25_hits:
            meta = self._chunks.get(uid)
            if meta is None:
                continue
            candidates_map.setdefault(
                uid,
                RetrievedChunk(
                    chunk_uid=uid, doc_id=meta.doc_id, doc_title=meta.doc_title,
                    section=meta.section, tags=meta.tags, content=meta.content,
                    rerank_bias=meta.rerank_bias,
                ),
            )

        fused = reciprocal_rank_fusion(
            ranked_lists=[dense_hits, bm25_hits],
            chunks_by_uid=candidates_map,
            k=settings.RRF_K,
            top_k=top_k,
            channel_names=("dense", "bm25"),
        )
        reranked = await asyncio.to_thread(simulate_gte_rerank, query, fused)
        best = reranked[0].rerank_score if reranked else 0.0
        hit = is_confident(best)
        reason = (
            "ok"
            if hit
            else f"best rerank score {best:.3f} below threshold "
                 f"{settings.RERANK_THRESHOLD}"
        )
        return RetrievalResult(
            query=query,
            hit=hit,
            total_candidates=len(fused),
            chunks=reranked,
            reason=reason,
        )


def _load_embedder_safe():
    from app.retrieval.embeddings import get_embedder

    return get_embedder()
