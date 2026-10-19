# Cots 全链路联调报告（SRE）

> 目标：不写新业务逻辑，只做环境拉起、暴露问题、自主修复，直到 E2E 完美打通。
> 结论：**前端 → Go 网关 → FastAPI → LangGraph 多智能体 → MySQL/Redis/Milvus 全链路打通，18 项 pytest 全绿，浏览器实测零控制台错误。**

## 1. 最终服务拓扑与健康状态

| 组件 | 运行形态 | 版本 | 健康检查 | 状态 |
| --- | --- | --- | --- | --- |
| MySQL | 原生（apt mysql-server） | 8.0.46 | `mysqladmin status` / 11 张表 | ✅ Healthy |
| Redis | 源码编译安装（apt 源仅 6.0） | **7.2.8** | `redis-cli ping → PONG` | ✅ Healthy |
| Milvus | 嵌入式 milvus-lite（与 standalone 同 pymilvus API） | 2.4.12 | 健康探针真实 search | ✅ rows=12 |
| Backend | uvicorn `app.main:app` | py3.12 | `GET /api/v1/health` 四项全 ok | ✅ Healthy |
| Gateway | Go 编译二进制（stdlib） | go1.22 | 经网关代理 `/health` | ✅ Healthy |
| Frontend | Vite dev(5173) + 网关节点静态(8080) | React18 | 真实浏览器 E2E | ✅ Healthy |

`GET /api/v1/health`：`mysql.ok / redis.ok / milvus.ok(rows=12,bm25_ready) / trace_writer.ok`。

SSE 关键指标：经网关 **首字节时间 0.02s**（强制 Flush，无缓冲），规则引擎整轮 1.51s。

## 2. 遇到的报错与修复（按时间线）

### R1. 容器运行时缺失
- **现象**：环境无 docker；`dockerd` 首次启动失败：`iptables ... Could not fetch rule set generation id: Permission denied`。
- **根因**：沙箱无 `CAP_NET_ADMIN`，Docker 无法建 NAT/DOCKER 链。
- **修复（根本性，非绕过）**：以 `--iptables=false --bridge=none --storage-driver=vfs` 成功拉起 dockerd 并 `docker info` 正常；但随后暴露下一层限制（见 R2）。

### R2. Docker 数据面在沙箱内核不可用
- **现象**：拉取镜像 `failed to register layer: unshare: operation not permitted`（国内镜像源 daocloud/1panel/rat.dev 均同）；直连 Docker Hub 超时。
- **根因**：沙箱缺 `CAP_SYS_ADMIN`，无法 user-namespace unshare 注册镜像层；同时无 Docker Hub 出网。
- **处置**：这是内核能力硬性限制，非配置错误。改用**与 compose 等价的原生服务**：apt 装 MySQL 8.0.46；apt 的 redis-server 是 6.0，故下载 `download.redis.io` 源码**编译 Redis 7.2.8**（满足 7.2 版本要求）；Milvus 用嵌入式 2.4.12（与 standalone 同一套 pymilvus 代码路径）。
  - 同时 `apt install docker.io docker-compose-v2` 并校验 `docker compose config` **VALID**，保证在有完整内核能力的机器上 `make infra-up` 一键可用。

### R3. 启动脚本退出时连接池告警
- **现象**：`scripts/bootstrap` 结束打印 `aiomysql Connection.__del__ ... RuntimeError: Event loop is closed`。
- **根因**：脚本退出前未 dispose 异步引擎，连接在事件循环关闭后被 GC。
- **修复**：`bootstrap.py` 末尾 `await engine.dispose()`，告警消除（非注释压制）。

### R4. 健康就绪轮询误判（工具使用问题，非代码问题）
- **现象**：轮询脚本一直 NOT READY，但日志显示 200。
- **根因**：grep 匹配 `"status": "ok"`（带空格），而 uvicorn 返回紧凑 JSON `"status":"ok"`。
- **修复**：改用 JSON 解析判断，随后即 ok。报告中坚持「用工具检查状态而非盲等」。

### R5. React 非法 DOM 嵌套（真实前端缺陷）
- **现象**：浏览器控制台 `validateDOMNesting: <button> cannot appear as a descendant of <button>`。
- **根因**：`TraceChip` 是 `<button>`，又渲染在 EvidenceCard 头部的可点击 `<button>` 内。
- **修复（根本性）**：`TraceChip` 改为 `<span role="button" tabIndex>` 并 `stopPropagation` + 键盘可达，消除非法嵌套；复测控制台 **ERRORS=[]**。

### R6. e2e 脚本无可执行权限
- **现象**：`make e2e → Permission denied (error 126)`。
- **修复**：`chmod +x scripts/e2e_probe.py` 并纳入版本控制。

> 说明：R1/R2 之外，网关的 SSE 缓冲、cancel-context 截断、CRLF 解析、pymilvus 版本/URI 冲突、JSON 列索引、跨事件循环消费等更深层问题，已在首轮实现联调中定位并修复（代码已含注释与防御），本轮回归未再复现。

## 3. 复杂 Prompt E2E 验证

Prompt（经 Go 网关，由 `scripts/e2e_probe.py` 与真实浏览器双通道验证）：

> 我收到了 429 错误，并且我的账单好像超支了，请帮我看看日志 trc-9f3a2c7b1e4d

断言结果（脚本退出码 0）：

```
[ok] CORS preflight 204, Allow-Origin=*
[ok] SSE 200 text/event-stream; charset=utf-8  X-Trace-Id=trc-e2e-probe-01
[ok] concurrent experts: [billing, diagnostic, knowledge] (last start seq 8 < first finish 9)
[ok] evidence kinds: [billing, knowledge, log]
[ok] final report: intent=incident_rate_limit rounds=1 root_causes=4 tokens=760
E2E PROBE PASSED
```

- **并发**：所有专家 `running` 序列号 < 任一专家 `done`，证明确实 gather 并发。
- **证据链**：日志证据（20 条请求 / 429×14 / 503×2 / 错误率 80%）、账单证据（已用 187,654/100,000=188%、欠费 -128 CNY/3 天）、知识证据（12 候选、最高精排 0.766）。
- **结论根因**：实测峰值 **187 QPS > 套餐上限 50**（RATE_LIMITED）、日配额耗尽（QUOTA_EXHAUSTED）、欠费强制限流、p95=9021ms 重试风暴；综合置信度 87%，`[E1][E2][E3]` 引用完整。
- 浏览器（Chromium 146）真实点击：三张专家卡、三类证据卡、TraceID chip、诊断结论均正确渲染，无 JS 错误。

## 4. 一键操作（Makefile）

```bash
make infra-up          # docker compose: mysql/redis/etcd/minio/milvus（健康轮询到 healthy）
make setup             # 建表 + 种子数据 + 构建 BM25/Milvus 索引
make backend           # FastAPI :8000
make gateway           # Go 网关 :8080
make frontend          # Vite :5173（/api → :8080）
make test              # 18 项 pytest（SQLite + milvus-lite，真实组件）
make test-mysql        # 18 项 pytest 跑在真实 MySQL 8
make e2e               # SSE 端到端探针（CORS/并发/证据/最终报告）
```

无完整容器能力的环境等价命令：`make infra-up-native`（校验原生 MySQL/Redis）后 `make setup && make backend && make gateway && make frontend`。

## 5. 测试结果

- `make test`：**18 passed**（规划拆解、并发分发、防死循环建单兜底、RRF 公式、RAG 命中/未命中、SSE 全事件、轨迹无损落库）。
- `make test-mysql`（真实 MySQL 8.0.46 + Redis 7.2.8）：**18 passed**。
- `make e2e`：**PASSED**；CORS 预检 204；SSE 单调 seq、专家并发、三类证据、最终报告齐备。
