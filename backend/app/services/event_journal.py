"""Redis-backed SSE event journal for cross-connection resume.

Every emitted SSE event is appended to ``cots:sse:<run_id>`` with a TTL; a
client that reconnects with ``Last-Event-ID: <n>`` gets everything after
sequence ``n`` replayed before live events resume.
"""

import json

from app.core.config import settings
from app.services.redis_client import get_redis


def _key(run_id: str) -> str:
    return f"cots:sse:{run_id}"


async def append_event(run_id: str, seq: int, event: str, data: dict) -> None:
    redis_client = get_redis()
    try:
        pipe = redis_client.pipeline()
        pipe.rpush(_key(run_id), json.dumps(
            {"seq": seq, "event": event, "data": data}, ensure_ascii=False, default=str
        ))
        pipe.expire(_key(run_id), settings.SSE_JOURNAL_TTL_SEC)
        await pipe.execute()
    except Exception:
        # In-memory EventBus history still covers same-process reconnect.
        pass


async def replay_events(run_id: str, after_seq: int) -> list[dict]:
    redis_client = get_redis()
    try:
        raw = await redis_client.lrange(_key(run_id), 0, -1)
    except Exception:
        return []
    out: list[dict] = []
    for item in raw:
        parsed = json.loads(item)
        if parsed["seq"] > after_seq:
            out.append(parsed)
    return out


async def journal_length(run_id: str) -> int:
    """Number of events already journaled (continuation buses start above)."""
    redis_client = get_redis()
    try:
        return await redis_client.llen(_key(run_id))
    except Exception:
        return 0
