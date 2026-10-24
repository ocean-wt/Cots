"""DiagnosticAgent toolset — real queries against the api_logs fact table."""

import re
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from app.db.base import utcnow
from app.db.models import ApiLog
from app.db.session import AsyncSessionLocal

TRACE_ID_PATTERNS = (
    re.compile(r"\btrc-[a-f0-9]{8,}\b", re.IGNORECASE),
    re.compile(r"\btrace[_-]?id[：:\s]+([a-f0-9\-]{8,})", re.IGNORECASE),
    re.compile(r"\b([a-f0-9]{16,32})\b", re.IGNORECASE),
)


def extract_trace_id(text: str) -> str | None:
    for pattern in TRACE_ID_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(match.lastindex) if match.lastindex else match.group(0)
    return None


async def fetch_logs_by_trace(trace_id: str, limit: int = 30) -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(ApiLog)
                .where(ApiLog.trace_id == trace_id)
                .order_by(ApiLog.created_at.asc(), ApiLog.id.asc())
                .limit(limit)
            )
        ).all()
        return [_log_row(r) for r in rows]


async def analyze_trace(trace_id: str) -> dict:
    """Aggregate status distribution, peak per-second QPS and error reasons."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(ApiLog)
                .where(ApiLog.trace_id == trace_id)
                .order_by(ApiLog.created_at.asc())
            )
        ).all()
        if not rows:
            return {"trace_id": trace_id, "found": False, "total": 0}

        status_counter = Counter(r.status_code for r in rows)
        endpoint_counter = Counter(r.endpoint for r in rows)
        per_second: Counter = Counter(
            r.created_at.replace(microsecond=0).isoformat() for r in rows
        )
        peak_second, peak_qps = per_second.most_common(1)[0]
        errors = [r for r in rows if r.status_code >= 400]
        error_reasons = Counter(r.error_message for r in errors if r.error_message)
        latencies = sorted(r.latency_ms for r in rows)
        p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0

        return {
            "trace_id": trace_id,
            "found": True,
            "total": len(rows),
            "status_breakdown": dict(sorted(status_counter.items())),
            "error_count": len(errors),
            "error_rate": round(len(errors) / len(rows), 4),
            "endpoints": dict(endpoint_counter),
            "peak_qps": peak_qps,
            "peak_second": peak_second,
            "p95_latency_ms": p95,
            "top_error_messages": error_reasons.most_common(5),
            "window_start": rows[0].created_at.isoformat(),
            "window_end": rows[-1].created_at.isoformat(),

            "sample_logs": [_log_row(r) for r in rows[:6]],
        }


async def recent_incidents(tenant_id: int, minutes: int = 60) -> list[dict]:
    since = utcnow() - timedelta(minutes=minutes)
    async with AsyncSessionLocal() as session:
        traces = (
            await session.execute(
                select(ApiLog.trace_id, func.count().label("hits"))
                .where(ApiLog.tenant_id == tenant_id)
                .where(ApiLog.created_at >= since)
                .where(ApiLog.status_code >= 400)
                .group_by(ApiLog.trace_id)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        return [
            {"trace_id": t[0], "error_hits": int(t[1])}
            for t in traces
        ]


_QPS_RE = re.compile(r"qps\s+(\d+)\s+exceeds\s+limit\s+(\d+)", re.IGNORECASE)


def _extract_qps(text: str) -> tuple[int | None, int | None]:
    match = _QPS_RE.search(text)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def derive_root_causes(analysis: dict) -> list[str]:
    """Deterministic root-cause tags from raw aggregated log evidence."""
    messages = [msg for msg, _ in analysis.get("top_error_messages", [])]
    reasons = " ".join(messages)
    causes: list[str] = []
    if "RATE_LIMITED" in reasons:
        # Prefer the tenant-wide QPS recorded by the limiter error message.
        observed, limit = _extract_qps(reasons)
        if observed:
            causes.append(
                f"瞬时 QPS 超限（实测峰值 {observed} QPS，超过套餐上限 "
                f"{limit} QPS，触发 RATE_LIMITED）"
            )
        else:
            causes.append(
                f"瞬时 QPS 超限（Trace 内峰值 {analysis['peak_qps']} QPS，"
                "触发 RATE_LIMITED）"
            )
    if "QUOTA_EXHAUSTED" in reasons:
        causes.append("日调用配额耗尽（QUOTA_EXHAUSTED）")
    if "ACCOUNT_OVERDUE" in reasons:
        causes.append("账户欠费触发写接口强制限流")
    if analysis.get("p95_latency_ms", 0) > 3000:
        causes.append(f"链路高延迟 p95={analysis['p95_latency_ms']}ms，疑似重试风暴")
    return causes


def _log_row(row: ApiLog) -> dict:
    return {
        "trace_id": row.trace_id,
        "method": row.method,
        "endpoint": row.endpoint,
        "status_code": row.status_code,
        "latency_ms": row.latency_ms,
        "error_message": row.error_message,
        "upstream": row.upstream,
        "request_body": row.request_body,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
