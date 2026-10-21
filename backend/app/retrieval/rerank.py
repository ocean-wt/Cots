"""Simulated ``gte-rerank`` cross-encoder stage.

A hosted gte-reranker is a cross-encoder producing a relevance probability in
[0, 1]. We reproduce that signal from the features a cross-encoder would
jointly attend over — dense semantic similarity, query-term coverage,
relative BM25 strength and title/tag exact matches — and output an identical
[0, 1] relevance probability interface. Constants are calibrated against the
real bge-small-zh vectors produced in-process.
"""

import re

from app.core.config import settings
from app.retrieval.schema import RetrievedChunk
from app.retrieval.tokenization import tokenize

_LATIN_OR_CJK = re.compile(r"[a-z0-9][a-z0-9_.\-+/]*|[一-鿿]")


def _query_terms(query: str) -> list[str]:
    # Keep unigrams only (no bigrams) so coverage stays interpretable.
    return [t for t in _LATIN_OR_CJK.findall(query.lower()) if len(t.strip()) > 0]


def _chunk_term_set(chunk: RetrievedChunk) -> set[str]:
    terms = set(tokenize(chunk.content))
    terms.update(tokenize(chunk.doc_title))
    terms.update(t.lower() for tag in chunk.tags for t in tokenize(tag))
    return terms


def simulate_gte_rerank(
    query: str,
    candidates: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    if not candidates:
        return []

    query_terms = _query_terms(query)
    query_term_set = set(query_terms)
    max_bm25 = max((c.bm25_score for c in candidates), default=1.0) or 1.0

    for chunk in candidates:
        terms = _chunk_term_set(chunk)
        if query_term_set:
            coverage = len(query_term_set & terms) / len(query_term_set)
        else:
            coverage = 0.0

        # bge quantized cosine typically lies in 0.25..0.75 for short docs
        dense_feature = max(0.0, min(1.0, (chunk.dense_score - 0.20) / 0.50))
        bm25_feature = chunk.bm25_score / max_bm25 if chunk.bm25_score > 0 else 0.0
        lexical_feature = 0.55 * coverage + 0.45 * bm25_feature

        title_terms = set(tokenize(chunk.doc_title))
        tag_terms = {t.lower() for tag in chunk.tags for t in tokenize(tag)}
        title_hits = len(query_term_set & title_terms)
        tag_hits = len(query_term_set & tag_terms)
        exact_bonus = min(0.15, 0.03 * title_hits + 0.02 * tag_hits)

        score = (
            0.55 * dense_feature
            + 0.35 * lexical_feature
            + exact_bonus
            + chunk.rerank_bias
        )
        chunk.rerank_score = round(max(0.0, min(1.0, score)), 6)

    return sorted(candidates, key=lambda c: c.rerank_score, reverse=True)


def is_confident(best_score: float) -> bool:
    return best_score >= settings.RERANK_THRESHOLD
