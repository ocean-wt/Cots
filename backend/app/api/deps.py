"""Request dependencies: identity from JWT, gateway token, or dev fallback."""

from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.core.security import decode_token


@dataclass
class Principal:
    tenant_id: int
    tenant_code: str
    user_id: int
    email: str
    trace_id: str | None = None


async def get_principal(
    authorization: str | None = Header(default=None),
    x_gateway_token: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_tenant_code: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
) -> Principal:
    # 1) A valid JWT is always accepted.
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = decode_token(token)
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid token: {exc}",
            ) from exc
        return _principal_from_claims(claims, x_trace_id)

    # 2) Gateway-injected headers are trusted ONLY with the shared secret.
    if x_tenant_id:
        if x_gateway_token != settings.GATEWAY_INTERNAL_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="identity headers require a valid X-Gateway-Token",
            )
        return Principal(
            tenant_id=int(x_tenant_id),
            tenant_code=x_tenant_code or "acme",
            user_id=int(x_user_id or 1),
            email=x_user_email or "ops@acme.example",
            trace_id=x_trace_id,
        )

    # 3) No identity at all: anonymous only allowed in trusted dev mode.
    if settings.ALLOW_DEV_PRINCIPAL and not settings.REQUIRE_INTERNAL_AUTH:
        return Principal(
            tenant_id=1, tenant_code="acme", user_id=1,
            email="ops@acme.example", trace_id=x_trace_id,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


def _principal_from_claims(claims: dict, trace_id: str | None) -> Principal:
    return Principal(
        tenant_id=int(claims.get("tenant_id", 1)),
        tenant_code=str(claims.get("tenant_code", "acme")),
        user_id=int(claims.get("sub", 1)),
        email=str(claims.get("email", "ops@acme.example")),
        trace_id=trace_id,
    )
