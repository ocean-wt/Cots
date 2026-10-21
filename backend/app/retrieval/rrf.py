"""Reciprocal Rank Fusion — hand-written.

``score(d) = sum over channels of 1 / (k + rank(d))`` — merges the dense and
the BM25 ranked lists without needing cross-channel score calibration.
"""

from app.retrieval.schema import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    chunks_by_uid: dict[str, RetrievedChunk],
    k: int = 60,
    top_k: int = 20,
    channel_names: tuple[str, ...] = ("dense", "bm25"),
) -> list[RetrievedChunk]:
    fused: dict[str, RetrievedChunk] = {}

    for channel_idx, ranked in enumerate(ranked_lists):
        channel = (
            channel_names[channel_idx]
            if channel_idx < len(channel_names)
            else f"channel-{channel_idx}"
        )
        for rank, (uid, raw_score) in enumerate(ranked, start=1):
            hit = chunks_by_uid.get(uid)
            if hit is None:
                continue
            contribution = 1.0 / (k + rank)
            if uid not in fused:
                fused[uid] = hit
                hit.rrf_score = contribution
                hit.channels = [channel]
            else:
                fused[uid].rrf_score += contribution
                fused[uid].channels.append(channel)
            if channel == "dense":
                hit.rank_dense = rank
                hit.dense_score = raw_score
            elif channel == "bm25":
                hit.rank_bm25 = rank
                hit.bm25_score = raw_score

    ordered = sorted(fused.values(), key=lambda h: h.rrf_score, reverse=True)
    return ordered[:top_k]
