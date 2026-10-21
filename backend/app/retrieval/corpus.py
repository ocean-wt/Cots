"""Authoritative seed knowledge corpus for the RAG subsystem.

Loaded into ``knowledge_chunks`` and then ingested into both retrieval
channels (BM25 inverted index + Milvus vector collection).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedDoc:
    doc_id: str
    title: str
    section: str
    tags: tuple[str, ...]
    content: str


SEED_DOCS: list[SeedDoc] = [
    SeedDoc(
        doc_id="runbook-429",
        title="HTTP 429 Too Many Requests 排障手册",
        section="错误码排查",
        tags=("429", "限流", "rate limit", "配额", "quota"),
        content=(
            "当 API 返回 HTTP 429 Too Many Requests 时，说明请求触发了租户级流控。"
            "排查顺序：第一步，使用响应头 X-Trace-Id 在 api_logs 中检索同一 TraceID 的全部请求，"
            "确认状态码分布、突增时间点与调用端点。第二步，核对租户 QPS 限制（tenants.qps_limit）"
            "与当日调用量（tenants.daily_quota），429 可能来自 QPS 超限或日配额耗尽。"
            "第三步，检查账单状态，账户欠费（tenants.overdue=true / balance_cents<0）会触发强制限流。"
            "常见根因：突发流量超过 QPS、重试风暴、定时任务并发、配额或欠费。"
        ),
    ),
    SeedDoc(
        doc_id="runbook-429",
        title="HTTP 429 Too Many Requests 排障手册",
        section="修复步骤",
        tags=("429", "重试", "指数退避", "升级配额"),
        content=(
            "429 修复动作：客户端应读取 Retry-After 响应头并执行指数退避（建议 1s/2s/4s，"
            "抖动 jitter 0.3），避免重试风暴；为突发流量增加客户端队列与令牌桶。"
            "若属于正常业务增长，在计费系统提交 QPS 升级工单或扩容日配额。"
            "欠费场景需完成充值，账单系统刷新余额后限流通常在 1 分钟内解除。"
            "修复后用相同 TraceID 链路验证 5xx/429 比例恢复到基线。"
        ),
    ),
    SeedDoc(
        doc_id="policy-rate-limit",
        title="租户限流策略与 QPS 配额说明",
        section="限流策略",
        tags=("限流", "QPS", "令牌桶", "流控"),
        content=(
            "网关采用令牌桶算法在租户维度做限流：free 套餐 10 QPS、pro 套餐 50 QPS、"
            "enterprise 套餐 200 QPS。超过阈值的请求直接返回 429 并附带 Retry-After。"
            "日调用量超过 daily_quota 后同样返回 429（错误体 code=QUOTA_EXHAUSTED），"
            "与 QPS 瞬时超限（code=RATE_LIMITED）在错误码上有区分，排障时先区分二者。"
        ),
    ),
    SeedDoc(
        doc_id="billing-faq",
        title="账单、欠费停服与充值 FAQ",
        section="计费",
        tags=("欠费", "账单", "充值", "余额", "停服"),
        content=(
            "租户账单按小时出账，余额 balance_cents 为负或 overdue=true 时进入欠费状态："
            "宽限期 2 小时内仅告警，超过宽限期后网关对写接口返回 402/429 并触发强制限流。"
            "充值到账后账单系统在下一个结算周期刷新状态；紧急情况下可由值班同学手动解除欠费标记。"
            "发票与账单明细在控制台「费用中心」下载。"
        ),
    ),
    SeedDoc(
        doc_id="trace-guide",
        title="TraceID 全链路排障指南",
        section="可观测性",
        tags=("TraceID", "链路追踪", "日志", "api_logs"),
        content=(
            "所有经过网关的请求都会被赋予全局唯一 TraceID（响应头 X-Trace-Id），"
            "并透传到后端与日志系统。排障时在 api_logs 表按 trace_id 检索可还原该次调用的"
            "方法、端点、状态码、耗时、错误信息与请求体。若同一 TraceID 出现大量 429，"
            "结合时间窗口内的 QPS 曲线判断是突发流量还是配额/欠费导致。"
        ),
    ),
    SeedDoc(
        doc_id="apikey-best-practice",
        title="API Key 使用最佳实践",
        section="安全",
        tags=("api key", "密钥", "401", "403"),
        content=(
            "API Key 以 sk- 前缀发放，服务端仅保存哈希。返回 401 表示密钥无效或已吊销；"
            "403 表示密钥作用域不足。建议按应用环境（production/staging）分别签发密钥，"
            "定期轮换，不要在前端代码中硬编码。密钥泄漏后立即在控制台吊销并重新签发。"
        ),
    ),
    SeedDoc(
        doc_id="runbook-500",
        title="HTTP 500 / 502 / 504 服务端错误排查",
        section="错误码排查",
        tags=("500", "502", "504", "超时", "upstream"),
        content=(
            "500 表示后端内部异常，需结合 TraceID 查看 error_message 与堆栈；"
            "502 通常是网关上游连接失败；504 表示上游处理超时（默认 30 秒空闲超时）。"
            "排查时先确认上游服务健康状态与依赖（MySQL/Redis/Milvus）连通性，"
            "再分析慢查询或冷启动。网关具备空闲超时兜底与非流式请求一次自动重试。"
        ),
    ),
    SeedDoc(
        doc_id="sdk-retry",
        title="SDK 重试、退避与幂等设计",
        section="SDK",
        tags=("重试", "退避", "幂等", "SDK"),
        content=(
            "官方 SDK 默认对 408/429/500/502/503/504 执行最多 3 次指数退避重试，"
            "基准间隔 500ms，倍率 2.0，抖动 0.2。写请求应携带 Idempotency-Key 保证幂等，"
            "避免重试造成重复建单或重复扣费。可通过客户端配置关闭或调整重试策略。"
        ),
    ),
    SeedDoc(
        doc_id="error-code-map",
        title="平台错误码总览",
        section="错误码",
        tags=("错误码", "429", "402", "401", "403", "500"),
        content=(
            "常见错误码：401 未认证、403 无权限、402 账户欠费、429 RATE_LIMITED 瞬时限流、"
            "429 QUOTA_EXHAUSTED 日配额耗尽、500 内部错误、502 上游不可达、504 上游超时。"
            "所有错误响应体均包含 code、message、trace_id 三个字段，trace_id 用于全链路定位。"
        ),
    ),
    SeedDoc(
        doc_id="ticket-sla",
        title="智能建单与工单 SLA 说明",
        section="工单",
        tags=("工单", "建单", "SLA", "兜底"),
        content=(
            "当知识库未命中或问题需要人工介入时，智能体会自动创建工单（source=agent_auto），"
            "并附带 TraceID、日志片段、账单状态与证据链。P1 工单 15 分钟响应、"
            "P2 工单 2 小时响应、P3 工单下个工作日响应。建单后用户可在控制台跟踪进度。"
        ),
    ),
    SeedDoc(
        doc_id="milvus-ops",
        title="Milvus 向量检索运维说明",
        section="运维",
        tags=("milvus", "向量", "检索", "etcd", "minio"),
        content=(
            "Milvus standalone 依赖 etcd 存储元数据、MinIO 存储段数据。检索为空时依次检查："
            "collection 是否已 load、embedding 维度是否一致（bge-small-zh 为 512 维）、"
            "索引 metric 是否为 IP（向量已 L2 归一化，内积等价余弦）。混合检索使用 RRF "
            "融合向量与 BM25 两路 Top20，再做精排。"
        ),
    ),
    SeedDoc(
        doc_id="webhook-guide",
        title="Webhook 事件订阅配置指南",
        section="集成",
        tags=("webhook", "回调", "签名", "事件"),
        content=(
            "在应用设置中配置 Webhook 地址后，工单状态变更、配额告警等事件会以 POST 推送，"
            "请求头 X-Cots-Signature 为 HMAC-SHA256 签名。接收方应校验签名并返回 2xx，"
            "平台对失败回调按指数退避重试最多 8 次。"
        ),
    ),
]
