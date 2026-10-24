"""Application configuration.

Every value is environment-overridable (``.env`` supported) so the exact same
code runs against the docker-compose topology (MySQL / Redis / Milvus
standalone) and the local development topology (SQLite / embedded
milvus-lite), with zero mocked components.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    ENV: str = Field(default="dev", description="dev | prod")
    PROJECT_NAME: str = "Cots"
    API_V1_STR: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ---- Auth -----------------------------------------------------------
    JWT_SECRET: str = "cots-dev-secret-change-me-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24
    # Identity headers (X-Tenant-Id ...) are trusted only when accompanied by
    # this shared gateway secret. Direct backend access then needs a JWT.
    GATEWAY_INTERNAL_TOKEN: str = "cots-internal-dev-token"
    REQUIRE_INTERNAL_AUTH: bool = False
    # Local/dev convenience: with no JWT and no gateway token, fall back to the
    # seeded demo principal. Must be false outside trusted networks.
    ALLOW_DEV_PRINCIPAL: bool = True

    # ---- Hardening ------------------------------------------------------
    INPUT_MAX_CHARS: int = 4000
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    GATEWAY_HEADER_TRUST: bool = True

    # ---- Storage --------------------------------------------------------
    # MySQL in docker:   mysql+aiomysql://cots:cots@mysql:3306/cots
    # Local embedded:    sqlite+aiosqlite:///./data/cots.db
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATA_DIR / 'cots.db'}"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- Milvus ---------------------------------------------------------
    # Empty / local .db path -> milvus-lite embedded engine; http://host:port
    # -> standalone. (Name intentionally avoids pymilvus's reserved MILVUS_URI.)
    COTS_MILVUS_URI: str = str(DATA_DIR / "milvus_lite.db")
    MILVUS_HOST: str = "milvus"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "knowledge_chunks"

    # ---- Embeddings / RAG ----------------------------------------------
    HF_ENDPOINT: str = "https://hf-mirror.com"
    EMBED_MODEL: str = "Xenova/bge-small-zh-v1.5"
    EMBED_ONNX_FILE: str = "onnx/model_quantized.onnx"
    EMBED_DIM: int = 512
    EMBED_CACHE_DIR: str = str(DATA_DIR / "models")
    # bge-zh official retrieval instruction prefix for queries
    EMBED_QUERY_INSTRUCTION: str = "为这个句子生成表示以用于检索相关文章："
    RETRIEVAL_TOP_K: int = 20
    RRF_K: int = 60
    RERANK_THRESHOLD: float = 0.40
    BM25_K1: float = 1.5
    BM25_B: float = 0.75

    # ---- LLM ------------------------------------------------------------
    # auto: openai -> anthropic -> deterministic rule engine
    LLM_PROVIDER: str = "auto"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_AUTH_TOKEN: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    LLM_TEMPERATURE: float = 0.2

    # ---- Agent orchestration -------------------------------------------
    AGENT_MAX_ROUNDS: int = 2
    AGENT_NODE_TIMEOUT_SEC: float = 60.0
    # Per-expert LLM analysis cap; on timeout the expert keeps its rule-based
    # summary and, crucially, its real tool evidence (node never loses data).
    AGENT_LLM_ANALYZE_TIMEOUT_SEC: float = 35.0
    TRACE_QUEUE_KEY: str = "cots:queue:agent_traces"
    TRACE_PROCESSING_KEY: str = "cots:queue:agent_traces:processing"
    SSE_JOURNAL_TTL_SEC: int = 600
    SSE_IDLE_TIMEOUT_SEC: float = 30.0

    # ---- Misc -----------------------------------------------------------
    CORS_ORIGINS: list[str] = ["*"]
    SEED_ON_STARTUP: bool = True

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def milvus_uri(self) -> str:
        return self.COTS_MILVUS_URI or str(DATA_DIR / "milvus_lite.db")

    @property
    def milvus_is_embedded(self) -> bool:
        # A *.db path uses embedded milvus-lite; an http(s) URL (or empty
        # value combined with MILVUS_HOST) targets a standalone service.
        return self.milvus_uri.endswith(".db")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
