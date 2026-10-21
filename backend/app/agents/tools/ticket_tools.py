"""SupportAgent toolset — real ticket creation in the tickets table."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.models import Ticket
from app.db.session import AsyncSessionLocal


async def create_support_ticket(
    tenant_id: int,
    title: str,
    detail: dict,
    trace_id: str | None = None,
    category: str = "technical",
    priority: str = "P2",
    source: str = "agent_auto",
) -> dict:
    async with AsyncSessionLocal() as session:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        daily_count = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.ticket_no.like(f"TKT-{today}-%"))
        )
        ticket_no = f"TKT-{today}-{int(daily_count or 0) + 1:04d}"
        ticket = Ticket(
            tenant_id=tenant_id,
            ticket_no=ticket_no,
            title=title[:255],
            category=category,
            priority=priority,
            status="open",
            trace_id=trace_id,
            source=source,
            detail=detail,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return {
            "ticket_no": ticket.ticket_no,
            "id": ticket.id,
            "title": ticket.title,
            "priority": ticket.priority,
            "status": ticket.status,
            "trace_id": ticket.trace_id,
        }
