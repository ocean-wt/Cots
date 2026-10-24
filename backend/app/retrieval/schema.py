"""Shared retrieval data structures."""

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class IndexedChunk:
    chunk_uid: str
    doc_id: str
    doc_title: str
    section: str
    tags: list[str]
    content: str
    embedding: np.ndarray | None = None
    rerank_bias: float = 0.0


@dataclass
class RetrievedChunk:
    chunk_uid: str
    doc_id: str
    doc_title: str
    section: str
    tags: list[str]
    content: str
    dense_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    rank_dense: int = -1
    rank_bm25: int = -1
    channels: list[str] = field(default_factory=list)
    rerank_bias: float = 0.0

    def to_evidence_payload(self) -> dict[str, Any]:
        return {
            "chunk_uid": self.chunk_uid,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "section": self.section,
            "tags": self.tags,
            "snippet": self.content[:280],
            "scores": {
                "dense": round(self.dense_score, 4),
                "bm25": round(self.bm25_score, 4),
                "rrf": round(self.rrf_score, 4),
                "rerank": round(self.rerank_score, 4),
            },
            "channels": self.channels,
        }


@dataclass
class RetrievalResult:
    query: str
    hit: bool
    total_candidates: int
    chunks: list[RetrievedChunk]
    reason: str = ""
