# Cots · 自主执行任务的超级智能

基于 **LLM + LangGraph Multi-Agent** 的生产级智能运维平台。用户只需给出模糊目标
（如「系统报 429 错误了」），Supervisor 主管智能体即自主完成意图识别、任务拆解、
**并发**调度多个专业智能体，跨日志系统、计费库与知识库收集证据，最终输出
**带证据链**的结论，并在知识未命中时自动建单兜底。

![topology](docs/architecture.svg)

## 架构总览

```
React18 (SSE 流水线可视化)
        │  text/event-stream
        ▼
Go 高性能网关 ── JWT 注入身份头 / 生成 TraceID / SSE 强制 Flush / 空闲超时兜底 / 熔断重试
        │
        ▼
FastAPI (SSE)
        │
LangGraph: START → supervisor(拆解) → dispatch(并发专家) → review ──► synthesize → END
                                         │  ┌──────────────┼──────────────┐
                                   DiagnosticAgent  BillingAgent  KnowledgeAgent
                                   (api_logs/TraceID) (配额/QPS/欠费) (Milvus+BM25 RAG)
                                         └──── 未命中 → SupportAgent 自动建单（第 2 轮）
        │                │                  │
   MySQL 8.0         Redis 7.2         Milvus 2.4 (+etcd/minio)
   11 张表          轨迹队列/SSE 续传      向量召回
```

### 专业智能体（各自独立 System Prompt + 专属真实工具集）

| Agent | 工具 | 数据源 |
| --- | --- | --- |
| `DiagnosticAgent` 排障专家 | `extract_trace_id` / `analyze_trace` / `recent_incidents` | MySQL `api_logs` |
| `BillingAgent` 账单专家 | `fetch_tenant_billing` | MySQL `tenants` |
| `KnowledgeAgent` 知识专家 | `hybrid_knowledge_search` | Milvus 向量 + BM25，手写 RRF 融合 + gte 精排 |
| `SupportAgent` 建单专家 | `create_support_ticket` | MySQL `tickets`（兜底轮次） |

- **真正并发**：`asyncio.gather` 同时派发，各专家独立出证、独立超时熔断，单点失败不拖垮整轮。
- **防死循环**：`MAX_ROUNDS=2` + LangGraph `recursion_limit`，review 仅允许一次建单兜底轮。
- **混合 RAG**：BGE-small-zh（ONNX Runtime 真实推理，512 维）向量 Top20 + 手写
  Okapi BM25 Top20 → **手写 RRF（k=60）** → 模拟 gte-rerank 精排；低于阈值返回
  `hit=False`，Supervisor 转入建单流程。
- **异步无损落库**：Agent 轨迹/Token 经 Redis 可靠队列（BRPOPLPUSH + ACK + 崩溃恢复）
  异步写入 `agent_execution_traces`。

## 一键启动（Docker Compose）

```bash
docker compose up -d --build
# 前端        http://localhost:5173
# 网关        http://localhost:8080
# 后端 API    http://localhost:8000  (docs: /docs)
# Milvus      19530 / 健康 9091，MinIO 控制台 9001
```

开箱即带一个真实的 429 事故场景（租户 `acme`、TraceID `trc-9f3a2c7b1e4d`、
配额耗尽 + 欠费 + 突发限流）。打开前端直接问：

> 系统报 429 错误了，traceID trc-9f3a2c7b1e4d，帮我紧急排查

可选环境变量：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `ANTHROPIC_API_KEY` …
未配置 LLM 时，系统使用确定性规则规划器/综合器，**全链路依旧真实可跑**。

## 本地开发（无 Docker）

依赖：Python 3.12、Node 20+、Go 1.22+、MySQL 8、Redis。

```bash
# 后端
cd backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
cp .env.example .env            # 默认指向本地 MySQL/Redis，Milvus 用嵌入式 milvus-lite
uv run uvicorn app.main:app --reload --port 8000

# 网关
cd gateway && go run .         # :8080 → http://127.0.0.1:8000

# 前端
cd frontend && npm install && npm run dev   # :5173（/api 代理到网关 :8080）
```

## 测试

```bash
cd backend
# 默认 SQLite + 嵌入式 Milvus + Redis db1（全部为真实组件，无 Mock）
uv run pytest
# 指向真实 MySQL 8：
COTS_TEST_DATABASE_URL='mysql+aiomysql://cots:cots123@127.0.0.1:3306/cots_test' \
  REDIS_URL='redis://localhost:6379/2' uv run pytest
```

覆盖：Supervisor 意图拆解、三专家并发分发、MAX_ROUNDS 防死循环与建单兜底、
RRF 融合公式、混合 RAG 命中/未命中、SSE 全事件流、轨迹异步无损落库。

## SSE 事件协议

`event: round`（拆解计划）→ `agent_action`（哪个 Agent 在执行什么/用什么工具）
→ `evidence`（结构化证据）→ `token`（打字机增量）→ `final`（证据链报告）→ `done`。
每条事件带单调 `id`，断线后通过 `GET /api/v1/chat/stream/{run_id}/resume?last_event_id=n`
（Redis 事件日志）续传，前端按 `Last-Event-ID` 自动重连。

## 目录

```
backend/   FastAPI + LangGraph + 混合 RAG（app/agents · app/retrieval · app/services）
gateway/   Go stdlib 网关（JWT/TraceID/SSE Flush/熔断）
frontend/  React18 + Vite + Tailwind + Framer Motion
docs/      架构图
```
