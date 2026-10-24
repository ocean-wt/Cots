"""Development token endpoint — mints the HS256 JWT the Go gateway verifies."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import Principal, get_principal
from app.core.security import issue_token
from app.db.models import User
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.post("/auth/dev-token")
async def dev_token(principal: Principal = Depends(get_principal)) -> dict:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.email == principal.email)
        )
        user_id = user.id if user else principal.user_id
        tenant_id = user.tenant_id if user else principal.tenant_id
    token = issue_token({
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "tenant_code": principal.tenant_code,
        "email": principal.email,
        "scope": "chat:write knowledge:read",
    })
    return {
        "access_token": token,
        "token_type": "Bearer",
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
