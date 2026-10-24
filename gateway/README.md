# Cots Gateway

纯 Go 标准库实现的边缘网关（无第三方依赖）。

- **JWT**：HS256 签名校验（`jwt.go`），解析后注入 `X-User-Id / X-Tenant-Id /
  X-Tenant-Code / X-User-Email`；`GATEWAY_DEV_MODE=true` 时放行匿名请求为演示租户。
- **TraceID**：透传合法的 `X-Trace-Id`，否则生成全局唯一 `trc-<24hex>`（`trace.go`）。
- **SSE 强制 Flush**：上游每个字节块读出后立即 `Flush()`，并关闭代理缓冲
  （`X-Accel-Buffering: no`），保证 agent 思考过程实时穿透（`main.go proxySSE`）。
- **空闲超时兜底**：`SSE_IDLE_TIMEOUT_SEC` 内无事件则向客户端补发
  `event: error` 兜底帧。
- **熔断与重试**（`circuit.go`）：连续失败达阈值打开熔断（半开探测）；
  幂等非流式请求（GET/HEAD/DELETE）失败自动重试一次。
- **CORS / SPA**：内置跨域头；设置 `FRONTEND_DIST` 可直接托管前端构建产物。

## 运行

```bash
go run .
# BACKEND_URL=http://127.0.0.1:8000 GATEWAY_ADDR=:8080
# GATEWAY_JWT_SECRET 与后端 JWT_SECRET 保持一致
```
