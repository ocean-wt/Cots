"""Milvus vector store.

Same ``pymilvus`` client API against two engines: an embedded milvus-lite
database file locally (``MILVUS_URI=.../milvus_lite.db``) and a Milvus
standalone service in docker-compose (``MILVUS_HOST`` / ``MILVUS_PORT``).
Vectors are L2-normalized embeddings indexed with inner-product, which is
cosine similarity on the unit sphere.
"""

import os
import threading

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MilvusVectorStore:
    _instance: "MilvusVectorStore | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        from pymilvus import DataType, MilvusClient

        if settings.milvus_is_embedded:
            # milvus-lite validates absolute filesystem URIs
            uri = os.path.abspath(settings.milvus_uri)
        elif settings.milvus_uri.startswith("http"):
            uri = settings.milvus_uri
        else:
            uri = f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        self.client = MilvusClient(uri=uri)
        self.collection = settings.MILVUS_COLLECTION
        self._ensure_collection(DataType)
        logger.info("Milvus ready uri=%s collection=%s", uri, self.collection)

    # ------------------------------------------------------------------ #
    def _ensure_collection(self, DataType) -> None:
        if self.client.has_collection(self.collection):
            self.client.load_collection(self.collection)
            return

        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("chunk_uid", DataType.VARCHAR, max_length=96)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=96)
        schema.add_field("doc_title", DataType.VARCHAR, max_length=512)
        schema.add_field("section", DataType.VARCHAR, max_length=512)
        schema.add_field("text", DataType.VARCHAR, max_length=9000)
        schema.add_field(
            "embedding", DataType.FLOAT_VECTOR, dim=settings.EMBED_DIM
        )

        index_params = self.client.prepare_index_params()
        # FLAT gives exact inner-product (cosine on normalized vectors) and
        # needs no training data; ideal up to the 10^5-chunk scale.
        index_params.add_index(
            field_name="embedding",
            index_type="FLAT",
            metric_type="IP",
        )
        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        self.client.load_collection(self.collection)

    # ------------------------------------------------------------------ #
    def count(self) -> int:
        # Prefer an actual query over get_collection_stats: milvus-lite's
        # stats path can hit an internal sqlite error even while search works.
        try:
            rows = self.client.query(
                self.collection, filter="pk >= 0", output_fields=["chunk_uid"],
                limit=16384,
            )
            return len(rows)
        except Exception:
            probe = self.search([0.0] * settings.EMBED_DIM, 1)
            return len(probe)

    def healthy(self) -> bool:
        try:
            self.search([0.0] * settings.EMBED_DIM, 1)
            return True
        except Exception:
            return False

    def upsert_chunks(
        self,
        uids: list[str],
        doc_ids: list[str],
        titles: list[str],
        sections: list[str],
        texts: list[str],
        embeddings: list[list[float]],
    ) -> int:
        if not uids:
            return 0
        quoted = ", ".join(f'"{uid}"' for uid in uids)
        self.client.delete(self.collection, filter=f"chunk_uid in [{quoted}]")
        entities = [
            {
                "chunk_uid": uid,
                "doc_id": doc_id,
                "doc_title": title[:500],
                "section": section[:500],
                "text": text[:8900],
                "embedding": vec,
            }
            for uid, doc_id, title, section, text, vec in zip(
                uids, doc_ids, titles, sections, texts, embeddings
            )
        ]
        result = self.client.insert(self.collection, data=entities)
        self.client.load_collection(self.collection)
        return int(result.get("insert_count", len(entities)))

    def search(
        self, query_vector: list[float], top_k: int
    ) -> list[tuple[str, float, dict]]:
        results = self.client.search(
            collection_name=self.collection,
            data=[query_vector],
            limit=top_k,
            output_fields=["chunk_uid", "doc_id", "doc_title", "section", "text"],
            search_params={"metric_type": "IP", "params": {"nprobe": 16}},
        )
        rows: list[tuple[str, float, dict]] = []
        for hit in results[0]:
            entity = hit.get("entity", {})
            rows.append((entity["chunk_uid"], float(hit.get("distance", 0.0)), entity))
        return rows

    def all_chunk_uids(self) -> set[str]:
        rows = self.client.query(
            self.collection, filter="pk >= 0", output_fields=["chunk_uid"]
        )
        return {r["chunk_uid"] for r in rows}


def get_vector_store() -> MilvusVectorStore:
    if MilvusVectorStore._instance is None:
        with MilvusVectorStore._lock:
            if MilvusVectorStore._instance is None:
                MilvusVectorStore._instance = MilvusVectorStore()
    return MilvusVectorStore._instance
