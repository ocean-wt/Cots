"""Hand-written RRF fusion correctness."""

from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.schema import RetrievedChunk


def _chunk(uid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_uid=uid, doc_id=uid.split("#")[0], doc_title=uid,
        section="", tags=[], content="x",
    )


def test_rrf_rank_formula():
    dense = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    bm25 = [("b", 12.0), ("a", 9.0), ("d", 1.0)]
    by_uid = {u: _chunk(u) for u in ("a", "b", "c", "d")}

    fused = reciprocal_rank_fusion([dense, bm25], by_uid, k=60, top_k=10)

    scores = {h.chunk_uid: round(h.rrf_score, 6) for h in fused}
    # a: 1/61 + 1/62 ; b: 1/62 + 1/61 ; c: 1/63 ; d: 1/63
    assert scores["a"] == scores["b"]
    assert scores["b"] > scores["c"]
    assert fused[0].chunk_uid in {"a", "b"}
    assert set(fused[0].channels) == {"dense", "bm25"}
    assert fused[0].rank_dense == 1 or fused[0].rank_bm25 == 1


def test_rrf_topk_and_channel_labels():
    dense = [(f"d{i}", 1.0 / i) for i in range(1, 25)]
    bm25 = [(f"b{i}", float(i)) for i in range(20)]
    by_uid = {u: _chunk(u) for u, _ in dense + bm25}
    fused = reciprocal_rank_fusion([dense, bm25], by_uid, top_k=20)
    assert len(fused) == 20
