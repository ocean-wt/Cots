"""Conversation history endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import Principal, get_principal
from app.db.models import Conversation, Message
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.get("/conversations")
async def list_conversations(principal: Principal = Depends(get_principal)) -> dict:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Conversation)
                .where(Conversation.tenant_id == principal.tenant_id)
                .order_by(Conversation.updated_at.desc())
                .limit(50)
            )
        ).all()
        return {"items": [
            {"id": r.id, "title": r.title, "status": r.status,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows
        ]}


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: int, principal: Principal = Depends(get_principal)
) -> dict:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.asc())
            )
        ).all()
        return {"items": [
            {"id": r.id, "role": r.role, "content": r.content,
             "trace_id": r.trace_id, "token_usage": r.token_usage,
             "structured": r.structured,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]}
