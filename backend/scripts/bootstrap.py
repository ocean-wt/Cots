"""Idempotent bootstrap: schema + seed data + hybrid retrieval index.

Usage (from backend/):  python -m scripts.bootstrap

NOTE: run this BEFORE starting the API server when using the embedded
milvus-lite engine — it is single-writer, so a running uvicorn process holds
the database lock. A standalone Milvus (docker compose, MILVUS_HOST) has no
such restriction.
"""

import asyncio
import sys

from app.core.logging import get_logger, setup_logging
from app.db.seed import seed_all
from app.db.session import AsyncSessionLocal, create_schema, engine
from app.retrieval.service import HybridRetrievalService

logger = get_logger("cots.bootstrap")


async def main() -> int:
    setup_logging()
    try:
        logger.info("creating/verifying schema ...")
        await create_schema()

        async with AsyncSessionLocal() as session:
            counts = await seed_all(session)
        logger.info("seed data: %s", counts)

        try:
            result = await HybridRetrievalService.instance().rebuild()
            logger.info("retrieval index: %s", result)
        except Exception as exc:
            if "Open local milvus failed" in str(exc) or "opened by another" in str(exc):
                logger.error(
                    "Embedded Milvus is locked by another process. Stop the "
                    "running API server before `make setup`, or use a standalone "
                    "Milvus via MILVUS_HOST. (%s)",
                    str(exc).splitlines()[0],
                )
                return 2
            raise
        logger.info("bootstrap complete")
        return 0
    finally:
        # Always release pooled connections before the loop closes.
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
