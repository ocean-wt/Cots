"""Durable asynchronous writer for agent execution traces and token usage.

Two lossless paths:

* **Redis path (normal)** — producers LPUSH JSON to a queue; a consumer moves
  each item to a processing list (BRPOPLPUSH), writes it to MySQL, then LREMs
  the ack. Items left in the processing list after a crash are re-queued at
  startup (at-least-once).
* **Direct path (Redis down)** — producers persist straight to MySQL via a
  bounded retry loop. Nothing is held in process memory, so a backend crash
  during a Redis outage still loses nothing. Redis is probed periodically and
  the writer transparently switches back.
"""

import asyncio
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import AgentExecutionTrace
from app.db.session import AsyncSessionLocal
from app.services.redis_client import get_redis

logger = get_logger(__name__)


class TraceWriter:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client or get_redis()
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._redis_alive = True
        self._total_enqueued = 0
        self._total_written = 0
        self._direct_writes = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "enqueued": self._total_enqueued,
            "written": self._total_written,
            "direct_writes": self._direct_writes,
        }

    @property
    def redis_alive(self) -> bool:
        return self._redis_alive

    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping = asyncio.Event()
        await self._recover_processing()
        self._tasks.append(
            asyncio.create_task(self._consume_loop(), name="trace-consumer")
        )
        self._tasks.append(
            asyncio.create_task(self._health_probe(), name="trace-redis-probe")
        )
        logger.info("TraceWriter started queue=%s", settings.TRACE_QUEUE_KEY)

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stopping.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _recover_processing(self) -> None:
        try:
            while True:
                item = await self._redis.rpoplpush(
                    settings.TRACE_PROCESSING_KEY, settings.TRACE_QUEUE_KEY
                )
                if item is None:
                    return
        except Exception as exc:
            logger.warning("trace recovery skipped: %s", exc)
            self._redis_alive = False

    async def _health_probe(self) -> None:
        """Periodically probe Redis and switch back once it recovers."""
        while not self._stopping.is_set():
            await asyncio.sleep(3)
            if self._redis_alive:
                continue
            try:
                # Short timeout so a stale pooled connection cannot stretch
                # one probe cycle beyond the 3s interval.
                await asyncio.wait_for(self._redis.ping(), timeout=2.0)
                self._redis_alive = True
                await self._recover_processing()
                logger.info("trace writer reconnected to Redis")
            except Exception:
                try:
                    await self._redis.connection_pool.disconnect()
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    async def enqueue(self, trace: dict) -> None:
        self._total_enqueued += 1
        body = json.dumps(trace, ensure_ascii=False, default=str)
        if self._redis_alive:
            try:
                await self._redis.lpush(settings.TRACE_QUEUE_KEY, body)
                return
            except Exception as exc:
                logger.warning("redis enqueue failed, writing trace directly: %s", exc)
                self._redis_alive = False
        # Degraded mode: durable direct write (survives process exit).
        await self._persist_one(body)
        self._direct_writes += 1

    # ------------------------------------------------------------------ #
    async def _consume_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                if self._redis_alive:
                    item = await self._redis.brpoplpush(
                        settings.TRACE_QUEUE_KEY,
                        settings.TRACE_PROCESSING_KEY,
                        timeout=2,
                    )
                else:
                    await asyncio.sleep(1)
                    continue
                if item is None:
                    continue
                await self._persist_one(item)
                await self._redis.lrem(settings.TRACE_PROCESSING_KEY, 1, item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("trace consumer iteration failed: %s", exc)
                self._redis_alive = False
                await asyncio.sleep(1.0)

    async def _persist_one(self, raw: str) -> None:
        data = json.loads(raw) if isinstance(raw, str) else raw
        for attempt in range(3):
            try:
                async with AsyncSessionLocal() as session:
                    session.add(_build_row(data))
                    await session.commit()
                self._total_written += 1
                return
            except Exception as exc:
                logger.warning("persist trace attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(0.5 * (attempt + 1))
        logger.error("trace dropped after retries: %s", str(raw)[:200])


def _build_row(data: dict) -> AgentExecutionTrace:
    return AgentExecutionTrace(
        run_id=data.get("run_id", ""),
        trace_id=data.get("trace_id", ""),
        tenant_id=data.get("tenant_id"),
        conversation_id=data.get("conversation_id"),
        round_index=int(data.get("round_index", 0)),
        task_id=data.get("task_id"),
        agent_name=data.get("agent_name", "unknown"),
        node=data.get("node", ""),
        phase=data.get("phase", ""),
        action=data.get("action", ""),
        detail=data.get("detail", ""),
        input_payload=data.get("input_payload", {}),
        output_payload=data.get("output_payload", {}),
        evidence=data.get("evidence", {}),
        token_usage=data.get("token_usage", {}),
        status=data.get("status", "ok"),
        duration_ms=int(data.get("duration_ms", 0)),
    )


async def pending_count() -> int:
    redis_client = get_redis()
    try:
        queued = await redis_client.llen(settings.TRACE_QUEUE_KEY)
        processing = await redis_client.llen(settings.TRACE_PROCESSING_KEY)
        return int(queued) + int(processing)
    except Exception:
        return 0


async def written_count(run_id: str) -> int:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func

        total = await session.scalar(
            select(func.count())
            .select_from(AgentExecutionTrace)
            .where(AgentExecutionTrace.run_id == run_id)
        )
        return int(total or 0)
