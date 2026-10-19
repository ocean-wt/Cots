# Cots operational entrypoints.
# Preferred path is Docker Compose; `*-native` targets run the exact same
# services directly on the host (used in environments without a container
# runtime with the required capabilities).

SHELL := /bin/bash
PY      ?= python3
VENV    ?= backend/.venv/bin/python
UV      ?= uv
GO      ?= go
NPM     ?= npm

COMPOSE := docker compose

export PYTHONPATH := backend

.PHONY: help infra-up infra-down infra-up-native setup backend gateway frontend \
        test test-mysql e2e stop clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- infrastructure
infra-up: ## Start MySQL/Redis/etcd/MinIO/Milvus via docker compose
	$(COMPOSE) up -d mysql redis etcd minio milvus
	@echo ">> waiting for infra health ..."
	@for i in $$(seq 1 90); do \
	  s=$$($(COMPOSE) ps --format '{{.Service}}:{{.Health}}' 2>/dev/null); \
	  echo "$$s" | grep -Eq 'mysql:healthy' || { sleep 2; continue; }; \
	  echo "$$s" | grep -Eq 'redis:healthy' || { sleep 2; continue; }; \
	  echo "$$s" | grep -Eq 'milvus:healthy' || { sleep 2; continue; }; \
	  echo ">> infra healthy"; exit 0; \
	done; echo "!! infra did not become healthy"; $(COMPOSE) ps; exit 1

infra-down: ## Stop compose infrastructure
	$(COMPOSE) down

infra-up-native: ## Use host MySQL/Redis (must already be installed/running)
	@redis-cli ping 2>/dev/null | grep -q PONG || \
	  redis-cli72 ping 2>/dev/null | grep -q PONG || (echo "!! redis not running"; exit 1)
	@mysqladmin status >/dev/null 2>&1 || (echo "!! mysql not running"; exit 1)
	@echo ">> native infra ready: Redis $$(redis-cli info server 2>/dev/null | awk -F: '/^redis_version/{print $$2}' | tr -d '[:space:]'), MySQL $$(mysql -Nse 'SELECT VERSION()' 2>/dev/null)"

# ------------------------------------------------------------------ setup/run
setup: ## Create schema + seed incident data + (re)build retrieval index (run BEFORE backend with embedded Milvus)
	cd backend && ./.venv/bin/python -m scripts.bootstrap

backend: ## Run FastAPI on :8000
	cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

gateway: ## Build and run Go gateway on :8080
	cd gateway && $(GO) run .

frontend: ## Run Vite dev server on :5173 (proxies /api -> :8080)
	cd frontend && $(NPM) run dev

frontend-build: ## Production build of the React app
	cd frontend && $(NPM) install --no-audit --no-fund && $(NPM) run build

# ------------------------------------------------------------------ tests/e2e
test: ## Backend pytest suite (SQLite + embedded Milvus)
	cd backend && PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q

test-mysql: ## Backend pytest suite against real MySQL 8
	cd backend && \
	COTS_TEST_DATABASE_URL='mysql+aiomysql://cots:cots123@127.0.0.1:3306/cots_test' \
	REDIS_URL='redis://localhost:6379/2' \
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/ -q

e2e: ## Run the SSE end-to-end probe through the Go gateway
	$(PYTHON) scripts/e2e_probe.py

stop: ## Stop natively-run services (pkill)
	-pkill -f 'uvicorn app.main'
	-pkill -f 'cots-gateway|go run.*gateway'

clean: stop ## Remove local runtime data
	rm -rf backend/data/milvus_lite.db
