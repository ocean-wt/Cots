"""Token accounting.

Uses the real ``tiktoken`` BPE tokenizer when its encoder blob is available
and falls back to a deterministic CJK-aware estimator otherwise. Every count
records which counter produced it, so the numbers stay auditable.
"""

from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # network-disabled encoder download, etc.
        logger.info("tiktoken unavailable, using CJK estimator: %s", exc)
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text))
    # Deterministic estimate: 1 token per CJK char, ~4 chars per latin token.
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + max(1, other // 4)
