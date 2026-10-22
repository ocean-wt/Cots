"""Ticket queries (rows created automatically by SupportAgent)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import Principal, get_principal
from app.db.models import Ticket
from app.db.session import AsyncSessionLocal

router = APIRouter()


class TicketCreate(BaseModel):
    title: str
    category: str = "technical"
    priority: str = "P2"
    detail: dict = {}


@router.get("/tickets")
async def list_tickets(
    limit: int = 20,
    principal: Principal = Depends(get_principal),
) -> dict:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Ticket)
                .where(Ticket.tenant_id == principal.tenant_id)
                .order_by(Ticket.id.desc())
                .limit(limit)
            )
        ).all()
        total = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.tenant_id == principal.tenant_id)
        )
        return {"total": total, "items": [_dict(r) for r in rows]}


@router.get("/tickets/{ticket_no}")
async def get_ticket(
    ticket_no: str,
    principal: Principal = Depends(get_principal),
) -> dict:
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(Ticket).where(Ticket.ticket_no == ticket_no)
        )
        if row is None or row.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="ticket not found")
        return _dict(row)


def _dict(row: Ticket) -> dict:
    return {
        "ticket_no": row.ticket_no,
        "title": row.title,
        "category": row.category,
        "priority": row.priority,
        "status": row.status,
        "trace_id": row.trace_id,
        "source": row.source,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
