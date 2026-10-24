"""Cots backend application entrypoint."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    auth,
    chat,
    conversations,
    health,
    knowledge,
    runs,
    tickets,
)
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.seed import seed_all
from app.db.session import AsyncSessionLocal, create_schema
from app.retrieval.service import HybridRetrievalService
from app.services.container import container
from app.services.reconciliation import reconcile_interrupted_runs
from app.services.redis_client import close_redis
from app.services.trace_writer import TraceWriter

logger = get_logger("cots.boot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)

    logger.info("creating database schema (%s)",
                "mysql" if not settings.is_sqlite else "sqlite")
    await create_schema()
    from app.agents.runtime import ensure_saver_schema

    await ensure_saver_schema()

    if settings.SEED_ON_STARTUP:
        async with AsyncSessionLocal() as session:
            counts = await seed_all(session)
        logger.info("seed data ready: %s", counts)

    await container.trace_writer.start()
    interrupted = await reconcile_interrupted_runs()
    if interrupted:
        logger.warning("reconciled %d interrupted run(s)", interrupted)

    try:
        result = await HybridRetrievalService.instance().rebuild()
        logger.info("hybrid retrieval index ready: %s", result)
    except Exception as exc:
        logger.exception("retrieval index rebuild failed (degraded): %s", exc)

    yield

    logger.info("shutting down: draining trace queue")
    await container.trace_writer.stop()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Autonomous multi-agent platform — supervisor + experts, "
                "hybrid RAG, evidence-chain SSE",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, auth, conversations, tickets, knowledge, runs):
    app.include_router(module.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat")


@app.get("/")
async def root() -> dict:
    return {
        "service": "cots-backend",
        "status": "running",
        "docs": "/docs",
        "api": settings.API_V1_STR,
    }
