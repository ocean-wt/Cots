"""BillingAgent toolset — real tenant quota / QPS / arrears data."""

from sqlalchemy import select

from app.db.models import Tenant
from app.db.session import AsyncSessionLocal


async def fetch_tenant_billing(tenant_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        used_today = int((tenant.extra or {}).get("used_today", 0))
        daily_quota = tenant.daily_quota
        return {
            "tenant_id": tenant.id,
            "tenant_code": tenant.tenant_code,
            "name": tenant.name,
            "plan": tenant.plan,
            "status": tenant.status,
            "qps_limit": tenant.qps_limit,
            "daily_quota": daily_quota,
            "used_today": used_today,
            "quota_remaining": max(0, daily_quota - used_today),
            "quota_exhausted": used_today >= daily_quota,
            "quota_usage_ratio": round(used_today / daily_quota, 3) if daily_quota else 0.0,
            "balance_cents": tenant.balance_cents,
            "balance_yuan": round(tenant.balance_cents / 100, 2),
            "overdue": tenant.overdue,
            "overdue_days": int((tenant.extra or {}).get("overdue_days", 0)),
            "currency": (tenant.extra or {}).get("currency", "CNY"),
        }


async def resolve_tenant_id_by_code(tenant_code: str) -> int | None:
    async with AsyncSessionLocal() as session:
        tenant = await session.scalar(
            select(Tenant).where(Tenant.tenant_code == tenant_code)
        )
        return tenant.id if tenant else None
