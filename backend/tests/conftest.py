"""Pytest configuration — fully real stack, no mocks.

Storage is driven by ``COTS_TEST_DATABASE_URL``: it defaults to an isolated
SQLite file, and in CI / docker it can point at the real MySQL 8.0 instance
(e.g. mysql+aiomysql://cots:cots123@127.0.0.1:3306/cots_test). Redis and the
embedded milvus-lite engine are the same processes the app uses. Expensive
resources (embedding model, Milvus collection) are real singletons and the
fixture itself is idempotent, so running per-test keeps the background trace
consumer on the same event loop as the test without cross-loop issues.
"""

import os
import pathlib
import tempfile

_TEST_DIR = pathlib.Path(tempfile.mkdtemp(prefix="cots-tests-"))
os.environ.setdefault("ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SEED_ON_STARTUP", "true")
os.environ.setdefault(
    "COTS_TEST_DATABASE_URL",
    f"sqlite+aiosqlite:///{_TEST_DIR / 'cots_test.db'}",
)
os.environ["DATABASE_URL"] = os.environ["COTS_TEST_DATABASE_URL"]
os.environ["COTS_MILVUS_URI"] = str(_TEST_DIR / "milvus_test.db")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import pytest_asyncio  # noqa: E402

from app.db import session as db_session  # noqa: E402
from app.db.seed import seed_all  # noqa: E402
from app.db.session import AsyncSessionLocal, create_schema  # noqa: E402
from app.retrieval.service import HybridRetrievalService  # noqa: E402
from app.services.container import container  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def stack():
    await create_schema()
    async with AsyncSessionLocal() as session:
        await seed_all(session)
    await container.trace_writer.start()
    await HybridRetrievalService.instance().rebuild()
    yield
    await container.trace_writer.stop()
    # Rebuild the pooled engine so every test owns its event loop's
    # connections (MySQL keeps pooled aiomysql connections loop-bound).
    await db_session.engine.dispose()
    new_engine = db_session.build_engine()
    db_session.engine = new_engine
    db_session.AsyncSessionLocal.configure(bind=new_engine)
