"""Real sentence embeddings via BAAI/bge-small-zh-v1.5 served by ONNX Runtime.

Model weights are downloaded from the HuggingFace mirror (``HF_ENDPOINT``)
and cached locally; inference runs in-process with no torch dependency.
Output vectors are mean-pooled and L2-normalized, so inner-product search in
Milvus is exactly cosine similarity.
"""

import os
import threading

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BGEEmbedder:
    _instance: "BGEEmbedder | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
        from huggingface_hub import hf_hub_download
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir_files = {
            "onnx_path": hf_hub_download(
                repo_id=settings.EMBED_MODEL,
                filename=settings.EMBED_ONNX_FILE,
                cache_dir=settings.EMBED_CACHE_DIR,
                endpoint=settings.HF_ENDPOINT,
            ),
            "tokenizer_path": hf_hub_download(
                repo_id=settings.EMBED_MODEL,
                filename="tokenizer.json",
                cache_dir=settings.EMBED_CACHE_DIR,
                endpoint=settings.HF_ENDPOINT,
            ),
        }
        self._tokenizer = Tokenizer.from_file(model_dir_files["tokenizer_path"])
        self._tokenizer.enable_truncation(max_length=512)
        self._session = ort.InferenceSession(
            model_dir_files["onnx_path"],
            providers=["CPUExecutionProvider"],
        )
        input_names = {i.name for i in self._session.get_inputs()}
        self._needs_token_types = "token_type_ids" in input_names
        logger.info(
            "BGE embedder ready model=%s inputs=%s",
            settings.EMBED_MODEL,
            sorted(input_names),
        )

    # ------------------------------------------------------------------ #
    def encode(
        self,
        texts: list[str],
        is_query: bool = False,
        batch_size: int = 16,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, settings.EMBED_DIM), dtype=np.float32)
        if is_query:
            texts = [
                t if t.startswith(settings.EMBED_QUERY_INSTRUCTION)
                else settings.EMBED_QUERY_INSTRUCTION + t
                for t in texts
            ]

        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.append(self._encode_batch(batch))
        return np.vstack(vectors).astype(np.float32)

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(list(texts), add_special_tokens=True)
        max_len = max(len(e.ids) for e in encodings)

        input_ids = np.array(
            [e.ids + [0] * (max_len - len(e.ids)) for e in encodings], dtype=np.int64
        )
        attention_mask = np.array(
            [e.attention_mask + [0] * (max_len - len(e.attention_mask))
             for e in encodings],
            dtype=np.int64,
        )
        ort_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if self._needs_token_types:
            ort_inputs["token_type_ids"] = np.zeros_like(input_ids)

        last_hidden = self._session.run(None, ort_inputs)[0]
        pooled = self._mean_pool(last_hidden, attention_mask)
        return self._l2_normalize(pooled)

    @staticmethod
    def _mean_pool(last_hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        mask = attention_mask[:, :, None].astype(np.float32)
        summed = (last_hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        return summed / counts

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-12, None)


def get_embedder() -> BGEEmbedder:
    """Process-wide singleton (model load is ~1s and ~100MB)."""
    if BGEEmbedder._instance is None:
        with BGEEmbedder._lock:
            if BGEEmbedder._instance is None:
                BGEEmbedder._instance = BGEEmbedder()
    return BGEEmbedder._instance
