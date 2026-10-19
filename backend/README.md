# Cots Backend

FastAPI + LangGraph 多智能体引擎 + 混合 RAG。

## 模块

- `app/agents/`
  - `graph.py` LangGraph 拓扑：supervisor → dispatch(并发) → review(建单兜底) → synthesize
  - `supervisor.py` 各图节点；`planner.py` 意图识别与任务拆解（LLM + 确定性规则双通道）
  - `diagnostic.py / billing.py / knowledge.py / support.py` 四个专业智能体
  - `base.py` 统一生命周期：独立 system prompt、工具调用推流、节点超时熔断
  - `tools/` 真实绑定工具（MySQL 日志、账单、混合检索、建单）
  - `events.py` SSE 事件总线；`synthesizer.py` 证据链综合（LLM 流式 / 规则兜底）
- `app/retrieval/`
  - `embeddings.py` BGE-small-zh-v1.5（ONNX Runtime，bge 查询指令前缀，L2 归一化）
  - `bm25.py` 手写 Okapi BM25（CJK unigram+bigram 分词）
  - `rrf.py` 手写 Reciprocal Rank Fusion；`rerank.py` 模拟 gte-rerank
  - `vector_store.py` pymilvus（standalone / 嵌入式 milvus-lite）；`service.py` 编排
- `app/services/`
  - `trace_writer.py` Redis 可靠队列异步无损落库（BRPOPLPUSH + ACK + 崩溃恢复）
  - `event_journal.py` SSE 断线续传；`workflow_state.py` 动态工作流检查点
- `app/db/` SQLAlchemy 2.0 模型（11 张表）、`seed.py` 429 事故种子、`scripts/init.sql`

## 配置

见 `.env.example`。未设置任何 LLM key 时，`LLM_PROVIDER=auto` 自动退回确定性规则引擎，
全链路（真实工具、证据、建单、SSE）照常运行。

## 运行 / 测试

```bash
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                      # SQLite + milvus-lite
```
