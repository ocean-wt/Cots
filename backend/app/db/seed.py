"""Idempotent seed data: a realistic 429 incident plus the knowledge corpus.

The scenario: tenant ``acme`` suffered a traffic spike on trace
``trc-9f3a2c7b1e4d`` returning 429s, its daily quota is exhausted and the
account is overdue — every expert agent has real facts to discover.
"""

import hashlib
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telemetry import count_tokens
from app.db.base import utcnow
from app.db.models import (
    ApiKey,
    ApiLog,
    Application,
    Conversation,
    KnowledgeChunk,
    Tenant,
    Ticket,
    User,
)
from app.retrieval.corpus import SEED_DOCS

DEMO_TRACE_ID = "trc-9f3a2c7b1e4d"
DEMO_TRACE_500 = "trc-5f1c9aa30b77"


def _chunk_uid(doc_id: str, index: int) -> str:
    return f"{doc_id}#chunk-{index:03d}"


async def seed_all(session: AsyncSession) -> dict[str, int]:
    """Insert seed data unless already present. Returns entity counts."""
    counts = {"tenants": 0, "users": 0, "applications": 0, "api_keys": 0,
              "api_logs": 0, "conversations": 0, "tickets": 0,
              "knowledge_chunks": 0}

    existing_tenant = await session.scalar(
        select(Tenant).where(Tenant.tenant_code == "acme")
    )
    if existing_tenant is None:
        tenant = Tenant(
            tenant_code="acme",
            name="Acme 示例科技有限公司",
            plan="pro",
            status="active",
            daily_quota=100_000,
            qps_limit=50,
            balance_cents=-12800,
            overdue=True,
            extra={"used_today": 187_654, "currency": "CNY",
                   "overdue_days": 3, "support_level": "enterprise-oncall"},
        )
        session.add(tenant)
        await session.flush()
        counts["tenants"] += 1
    else:
        tenant = existing_tenant

    user = await session.scalar(select(User).where(User.email == "ops@acme.example"))
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email="ops@acme.example",
            display_name="运维负责人",
            role="admin",
            extra={"phone": "13800000000"},
        )
        session.add(user)
        await session.flush()
        counts["users"] += 1

    app = await session.scalar(
        select(Application).where(Application.app_code == "acme-chatbot")
    )
    if app is None:
        app = Application(
            tenant_id=tenant.id,
            app_code="acme-chatbot",
            name="Acme 智能客服",
            environment="production",
            config={"framework": "langchain", "region": "cn-north-1"},
        )
        session.add(app)
        await session.flush()
        counts["applications"] += 1

    key_hash = hashlib.sha256("sk-demo-acme-0001".encode()).hexdigest()
    existing_key = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    if existing_key is None:
        session.add(ApiKey(
            tenant_id=tenant.id,
            application_id=app.id,
            key_prefix="sk-demo",
            key_hash=key_hash,
            name="production-default",
            scopes=["chat:write", "knowledge:read"],
            status="active",
        ))
        counts["api_keys"] += 1

    convos = await session.scalar(
        select(func.count()).select_from(Conversation).where(
            Conversation.tenant_id == tenant.id
        )
    )
    if convos == 0:
        session.add(Conversation(
            tenant_id=tenant.id, user_id=user.id,
            title="生产环境 429 故障协同处理", status="active",
        ))
        counts["conversations"] += 1

    log_count = await session.scalar(
        select(func.count()).select_from(ApiLog).where(
            ApiLog.trace_id == DEMO_TRACE_ID
        )
    )
    if log_count == 0:
        session.add_all(_build_incident_logs(tenant.id, app.id))
        counts["api_logs"] += 1

    tickets_count = await session.scalar(select(func.count()).select_from(Ticket))
    if tickets_count == 0:
        session.add(Ticket(
            tenant_id=tenant.id,
            ticket_no="TKT-20261020-0001",
            title="历史工单：偶发 504 网关超时",
            category="technical",
            priority="P3",
            status="resolved",
            source="console",
            detail={"note": "上游冷启动导致，已通过预热解决"},
        ))
        counts["tickets"] += 1

    existing_chunks = await session.scalar(
        select(func.count()).select_from(KnowledgeChunk)
    )
    if existing_chunks == 0:
        for doc in SEED_DOCS:
            same_doc = [d for d in SEED_DOCS if d.doc_id == doc.doc_id]
            idx = same_doc.index(doc)
            session.add(KnowledgeChunk(
                chunk_uid=_chunk_uid(doc.doc_id, idx),
                doc_id=doc.doc_id,
                doc_title=doc.title,
                chunk_index=idx,
                section=doc.section,
                tags=list(doc.tags),
                content=doc.content,
                token_count=count_tokens(doc.content),
            ))
            counts["knowledge_chunks"] += 1

    await session.commit()
    return counts


def _build_incident_logs(tenant_id: int, app_id: int) -> list[ApiLog]:
    base = utcnow() - timedelta(minutes=47)
    rows: list[ApiLog] = []

    # Healthy traffic right before the spike
    for i in range(4):
        rows.append(ApiLog(
            tenant_id=tenant_id, application_id=app_id,
            trace_id=DEMO_TRACE_ID,
            method="POST", endpoint="/v1/chat/completions",
            status_code=200, latency_ms=180 + i * 12,
            request_body='{"message":"你好，介绍一下配额"}',
            error_message=None, upstream="backend-pool-a",
            created_at=base + timedelta(seconds=i * 6),
        ))

    # The 429 burst — QPS far beyond the 50 QPS plan limit
    burst_messages = [
        "429 RATE_LIMITED: tenant qps 187 exceeds limit 50",
        "429 RATE_LIMITED: token bucket exhausted, retry_after=1",
        "429 QUOTA_EXHAUSTED: daily quota 100000 exceeded, used 187654",
        "429 ACCOUNT_OVERDUE: tenant balance -12800 CNY, write endpoints throttled",
    ]
    for i in range(14):
        ts = base + timedelta(seconds=30 + i * 2)
        rows.append(ApiLog(
            tenant_id=tenant_id, application_id=app_id,
            trace_id=DEMO_TRACE_ID,
            method="POST", endpoint="/v1/chat/completions",
            status_code=429,
            latency_ms=8 if i % 3 else 22,
            request_body='{"message":"系统报 429 错误了"}' if i == 0
            else '{"message":"继续请求 / 重试"}',
            error_message=burst_messages[i % len(burst_messages)],
            upstream="gateway-limiter",
            created_at=ts,
        ))

    # Tail: a couple of server errors from the retry storm
    for i in range(2):
        rows.append(ApiLog(
            tenant_id=tenant_id, application_id=app_id,
            trace_id=DEMO_TRACE_ID,
            method="POST", endpoint="/v1/chat/completions",
            status_code=503, latency_ms=9021,
            request_body='{"message":"重试"}',
            error_message="503 SERVICE_UNAVAILABLE: upstream worker pool saturated",
            upstream="backend-pool-b",
            created_at=base + timedelta(seconds=62 + i * 3),
        ))

    # A separate, unrelated 500 trace (so diagnosis must discriminate by TraceID)
    rows.append(ApiLog(
        tenant_id=tenant_id, application_id=app_id,
        trace_id=DEMO_TRACE_500,
        method="GET", endpoint="/v1/knowledge/search",
        status_code=500, latency_ms=12044,
        request_body=None,
        error_message="500 INTERNAL: milvus collection not loaded: knowledge_chunks",
        upstream="backend-pool-a",
        created_at=base + timedelta(minutes=12),
    ))
    rows.append(ApiLog(
        tenant_id=tenant_id, application_id=app_id,
        trace_id=DEMO_TRACE_500,
        method="GET", endpoint="/v1/knowledge/search",
        status_code=200, latency_ms=230,
        request_body=None,
        error_message=None,
        upstream="backend-pool-a",
        created_at=base + timedelta(minutes=18),
    ))
    return rows
