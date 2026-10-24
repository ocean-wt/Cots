"""Hybrid retrieval pipeline tests (BM25 + Milvus + RRF + rerank)."""

import pytest

from app.retrieval.bm25 import BM25Index
from app.retrieval.schema import IndexedChunk
from app.retrieval.service import HybridRetrievalService
from app.retrieval.tokenization import tokenize

pytestmark = pytest.mark.usefixtures("stack")


async def test_429_query_hits_real_runbook():
    result = await HybridRetrievalService.instance().retrieve(
        "429 限流 配额 欠费 怎么排查", top_k=20
    )
    assert result.hit is True, result.reason
    top = result.chunks[0]
    assert top.rrf_score > 0
    assert "429" in (top.content + top.doc_title + " ".join(top.tags)) or \
           "限流" in top.content
    assert top.dense_score > 0 or top.bm25_score > 0


async def test_bm25_chinese_tokenization_and_ranking():
    chunks = [
        IndexedChunk("d1#c0", "d1", "429 手册", "", ["429"],
                     "429 表示请求过多，触发租户限流与配额策略"),
        IndexedChunk("d2#c0", "d2", "Webhook 指南", "", ["webhook"],
                     "Webhook 回调签名使用 HMAC SHA256"),
    ]
    index = BM25Index()
    index.fit(chunks)
    hits = index.search("429 限流", top_k=2)
    assert hits[0][0] == "d1#c0"
    assert tokenize("429限流")  # latin + CJK coverage


async def test_low_score_miss_triggers_ticket_path():
    result = await HybridRetrievalService.instance().retrieve(
        "龘靐齉齾爩灪厵 plokijuhygt qazwsxedcr", top_k=20
    )
    assert result.hit is False
    if result.chunks:
        assert result.chunks[0].rerank_score < 0.40


async def test_vector_channel_returns_chunks():
    from app.retrieval.embeddings import get_embedder
    from app.retrieval.vector_store import get_vector_store

    embedder = get_embedder()
    store = get_vector_store()
    vec = embedder.encode(["429 限流 配额"], is_query=True)[0].tolist()
    rows = store.search(vec, top_k=5)
    assert rows, "Milvus collection must contain seeded vectors"
    uid, score, _ = rows[0]
    assert isinstance(uid, str) and score > 0
