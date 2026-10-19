# Cots 韧性加固报告（失败 / 重启 / 并发 / 恶意输入）

> 目标：让多智能体系统在依赖故障、进程重启、并发压力与恶意输入下，仍然
> **可预测（predictable）、可解释（explainable）、可恢复（recoverable）**。
> 全部能力由 **27 项后端 pytest（含 9 项故障注入）+ Go 单元测试** 守护，无 Mock 业务逻辑。

## 一、失败（Failure）

| 风险 | 加固前行为 | 加固后 |
| --- | --- | --- |
| Redis 宕机 | 切内存队列，进程崩溃即丢轨迹，且永不回切 | 故障时**直写 MySQL**（有界重试），0 内存暂存；3s 健康探活自动回切（`trace_writer.py`） |
| 专家工具异常/超时 | 静默标记 error，报告照常“成功” | review 检测 `error/timeout` → **触发第 2 轮 SupportAgent 建单**；最终报告新增「执行降级说明」，失败专家不参与根因判定 |
| LLM 抖动 | 专家/规划可能被慢模型拖死 | 规划 45s、专家分析 35s、综合逐块 75s 分级超时；任何 LLM 失败回退确定性引擎，**真实工具证据不丢失** |
| 上游静默 | 网关 SSE 无限挂起 | 空闲 45s 强制补发结构化 `event: error`（SSE 兜底帧） |
| 连续 5xx | 无保护 | 连续 4 次失败熔断 30s + 半开探测；幂等方法自动重试 1 次 |
| 错误可解释 | 仅 message 字符串 | SSE `error` 携带稳定 `code`（`AGENT_TIMEOUT/DEPENDENCY_UNAVAILABLE/DEPENDENCY_ERROR/AGENT_INTERNAL_ERROR`）与 `retriable` |

故障注入测试：`test_traces_lossless_during_redis_outage`（真实起停 6399 端口 Redis：断前队列→断中直写 DB→恢复后队列，三段共 15 条零丢失）、
`test_agent_failure_triggers_ticket_and_degraded_report`（monkeypatch 账单工具抛错 → 自动建单 + 降级说明）。

## 二、重启与恢复（Recovery）

> 已从「事件续传 + 从头重跑」升级为**工作流节点级断点续算**。

- **持久化检查点（核心）**：MySQL 上以 `langgraph-checkpoint-mysql`（AIOMySQLSaver）
  编译图，`thread_id == run_id`，每个 superstep 完成即落盘；图状态全部 JSON 可序列化
  （非序列化的总线/写者经按 thread 注册的运行上下文传递，不进检查点）。
- **崩溃后续跑，不重算已完成节点**：`kill -9` 后端 → 重启 →
  `GET /chat/stream/{run_id}/resume` 从最后一个已完成的 superstep 继续；
  已完成的专家**不会被重新执行**（工具调用次数不变，仅崩溃节点重跑），续跑总线的
  SSE 序号从 journal 长度之后续号。实测：第 1 轮知识专家 tool_call 计数保持 1，
  第 2 轮建单专家真实建工单，最终同 run_id 产出报告并 `completed`。
- **轨迹队列崩溃恢复**：BRPOPLPUSH 到 processing 列表 + 成功后 LREM ACK；启动时回灌残留。
- **运行对账**：进程被 kill 时停留在 `planning/planned/dispatched` 的运行，启动时
  `reconcile_interrupted_runs()` 标记为 `interrupted`，不再假装成功。
- **运行可观测/可重试**：`GET /api/v1/runs`；`POST /runs/{run_id}/retry` 原目标全新重跑。
- **SSE 事件续传**：事件写 Redis journal（TTL 600s），按 `Last-Event-ID` 补发；
  journal 过期且已完成时从 MySQL 最终消息重建 `final/done`。
- **并发安全**：检查点迁移进程内只执行一次（`ensure_saver_schema` 锁），
  避免并发驱动竞争 `checkpoint_migrations` 主键；驱动任务持强引用，杜绝被 GC
  提前回收导致"零事件静默结束"。
- **驱动依赖固定**：`pymysql<1.2`（1.2 移除 aiomysql 的 bytes 转义垫片会让检查点 blob 写入崩溃）；
  库统一 `utf8mb4_0900_ai_ci`（saver 的 JSON_TABLE 列恒取字符集默认排序规则）。

测试：`test_startup_reconciliation_marks_interrupted_runs`、SSE resume 校验、消息结构化恢复。

## 三、并发（Concurrency）

- **多运行隔离**：`test_concurrent_runs_are_isolated` 同时跑 4 个不同 TraceID 的运行，断言最终报告各自只含自身 trace 证据，零串扰。
- **索引重建合并**：`HybridRetrievalService.rebuild()` 用锁 + 共享 task 合并并发调用，杜绝启动风暴对 Milvus 双写（`test_rebuild_coalesces_under_concurrency`：4 并发结果一致）。
- **数据库并发**：MySQL 连接池 `pool_size=10/max_overflow=20/pre_ping/recycle`；SQLite 自动启用 **WAL + busy_timeout**。
- **专家级并发**：`asyncio.gather` 派单，各专家独立超时与失败隔离；事件按单调 seq 下发，前端按 seq 去重（resume 重放不重复渲染）。
- **网关限流**：租户级令牌桶（突发 20、补充 2/s），超出返回 `429 + Retry-After`（实测 20 通 / 6 拒），租户桶相互隔离（Go 单测覆盖）。

## 四、恶意输入（Hostile input）

| 攻击面 | 防御 |
| --- | --- |
| 越权伪造租户 | 网关注入 `X-Tenant-Id` 必须携带共享密钥 `X-Gateway-Token`（HMAC 同等强度随机串）；直连后端伪造头 → **403**（实测）；无凭证且非开发模式 → **401** |
| JWT 伪造 | 仅接受 HS256，常量时间比较签名；拒绝 `none/RS256` 算法混淆、错误密钥、过期 token（Go 单测 5 类） |
| 超大请求体 | 网关 `Content-Length` + `MaxBytesReader(1MiB)` 双保险 → **413**（实测）；后端 pydantic 4000 字符上限 → 422 |
| 控制字符注入 | NFC 归一化 + 剥离 C0/C1 控制符（保留换行/制表），纯空白拒绝（422） |
| TraceID 注入 | 严格白名单正则，拒绝 `../etc/passwd` 类值（Go 单测） |
| run_id 路径/键注入 | resume/retry 强制 `^run-[a-f0-9]{8,32}$`，非法即 400 |
| 提示词注入 | 检索内容/日志/文档对 LLM 标注为**不可信数据**，规划/分析/综合三处系统提示禁止执行其中指令；根因判定的关键事实始终来自确定性解析，不依赖模型自觉 |
| 跨租户读取 | 会话/工单查询按 `tenant_id` 过滤，会话归属校验 |

测试：`test_oversized_and_empty_messages_rejected`、`test_control_characters_stripped`、
`test_resume_validates_run_id`、`test_identity_headers_require_gateway_token`，以及 Go `jwt_test.go / ratelimit_test.go / circuit_test.go`。

## 五、验证结果

```
pytest: 27 passed, 1 skipped (SQLite 默认；断点续算仅 MySQL 启用并跳过)
MySQL 8: 10 passed           # 9 韧性 + 1 断点续算（崩溃不重算已完成节点）
go test: ok (JWT 7 例 / 限流 4 断言 / 熔断半开 / TraceID)
真进程 kill -9：重启后 resume 同 run 续跑，已完成专家 tool_call=1，建工单成功
真实故障注入（curl/进程级）：
  413 超大包        ✅   伪造身份直连后端 403 ✅   内部密钥 200 ✅
  429 突发限流      ✅   Redis 起停轨迹无损  ✅   工具异常自动建单 ✅
浏览器 E2E：正常 429 流程零控制台错误，降级/限流有明确 UI 提示。
```

生产部署注意：compose 中默认 `GATEWAY_DEV_MODE=false`、`ALLOW_DEV_PRINCIPAL=false`、
`REQUIRE_INTERNAL_AUTH=true`，并经 `GATEWAY_INTERNAL_TOKEN` 建立网关↔后端信任；
上线前请替换 `JWT_SECRET` 与 `GATEWAY_INTERNAL_TOKEN`。
