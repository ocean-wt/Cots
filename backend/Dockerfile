FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    EMBED_CACHE_DIR=/app/data/models

WORKDIR /app

# System packages required at runtime by some wheels (curl for healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Pre-fetch the real embedding model into the image (bge-small-zh, ~24MB)
RUN python -c "from app.retrieval.embeddings import get_embedder; get_embedder()"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=8s --start-period=90s --retries=10 \
  CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
