"""Hand-written Okapi BM25 (no third-party search library involved).

Implements document-length normalization, IDF with the standard
``log(1 + (N - df + 0.5) / (df + 0.5))`` smoothing and field boosts for
title / section / tags.
"""

import math
from collections import Counter

from app.core.config import settings
from app.retrieval.schema import IndexedChunk
from app.retrieval.tokenization import tokenize

_TITLE_BOOST = 3.0
_SECTION_BOOST = 1.5
_TAG_BOOST = 2.0


class BM25Index:
    def __init__(self, k1: float = settings.BM25_K1, b: float = settings.BM25_B):
        self.k1 = k1
        self.b = b
        self._chunks: list[IndexedChunk] = []
        self._doc_freqs: list[Counter] = []
        self._doc_lens: list[float] = []
        self._df: Counter = Counter()
        self._avg_len: float = 0.0
        self._idf: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    def fit(self, chunks: list[IndexedChunk]) -> None:
        self._chunks = chunks
        self._doc_freqs = []
        self._doc_lens = []
        self._df = Counter()

        for chunk in chunks:
            body = tokenize(chunk.content)
            title = tokenize(chunk.doc_title)
            section = tokenize(chunk.section)
            tags = tokenize(" ".join(chunk.tags))
            counts = Counter(body)
            for tok in title:
                counts[tok] += _TITLE_BOOST
            for tok in section:
                counts[tok] += _SECTION_BOOST
            for tok in tags:
                counts[tok] += _TAG_BOOST
            self._doc_freqs.append(counts)
            self._doc_lens.append(sum(counts.values()))
            for term in counts:
                self._df[term] += 1

        n_docs = len(chunks)
        self._avg_len = (sum(self._doc_lens) / n_docs) if n_docs else 0.0
        self._idf = {
            term: math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for term, df in self._df.items()
        }

    # ------------------------------------------------------------------ #
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if not self._chunks:
            return []
        query_terms = tokenize(query)
        scored: list[tuple[str, float]] = []
        for idx, freqs in enumerate(self._doc_freqs):
            score = 0.0
            doc_len = self._doc_lens[idx]
            norm = 1 - self.b + self.b * (doc_len / (self._avg_len or 1.0))
            for term in query_terms:
                tf = freqs.get(term, 0.0)
                if tf == 0.0:
                    continue
                idf = self._idf.get(term, 0.0)
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * norm)
            if score > 0:
                scored.append((self._chunks[idx].chunk_uid, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    @property
    def size(self) -> int:
        return len(self._chunks)
