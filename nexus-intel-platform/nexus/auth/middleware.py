from __future__ import annotations
import logging
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from nexus.config import settings

logger    = logging.getLogger(__name__)
_bearer   = HTTPBearer(auto_error=True)


class CurrentUser(BaseModel):
    analyst_id:  str
    clearance:   str   # UNCLASSIFIED | CUI | SECRET | TOP_SECRET
    roles:       list[str]
    sub:         str


@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    """Fetch JWKS from Keycloak (cached; refresh by clearing lru_cache)."""
    resp = httpx.get(settings.KEYCLOAK_JWKS_URI, timeout=5)
    resp.raise_for_status()
    return resp.json()


async def require_clearance(
    creds: HTTPAuthorizationCredentials = Security(_bearer),
) -> CurrentUser:
    """
    FastAPI dependency. Validates JWT, returns CurrentUser.
    Raises HTTP 401 on invalid/expired token.
    Raises HTTP 403 if clearance claim is missing or unrecognised.
    """
    token = creds.credentials
    try:
        # RS256 — Keycloak signs with RS256 by default
        payload = jwt.decode(
            token,
            _get_jwks(),
            algorithms=["RS256"],
            audience=settings.JWT_AUDIENCE,
            options={"verify_exp": True},
        )
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from e

    clearance = payload.get("nexus_clearance")
    if clearance not in {"UNCLASSIFIED", "CUI", "SECRET", "TOP_SECRET"}:
        raise HTTPException(
            status_code=403, detail="Missing or invalid clearance claim"
        )

    return CurrentUser(
        analyst_id = payload["nexus_analyst_id"],
        clearance  = clearance,
        roles      = payload.get("roles", []),
        sub        = payload["sub"],
    )


class ClearanceMiddleware:
    """
    ASGI middleware that sets app.nexus.clearance PostgreSQL session variable
    after JWT validation, enabling RLS policy enforcement at the DB layer.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            from nexus.deps import get_db_pool
            pool = await get_db_pool()

            # Extract clearance from JWT (best-effort; auth route validates fully)
            auth_hdr = dict(scope.get("headers", [])).get(b"authorization", None)
            clearance = "UNCLASSIFIED"
            if auth_hdr:
                try:
                    token = auth_hdr.decode().split(" ", 1)[1]
                    p     = jwt.get_unverified_claims(token)
                    clearance = p.get("nexus_clearance", "UNCLASSIFIED")
                except Exception:
                    pass

            # Set per-connection session variable for RLS
            scope["nexus.clearance"] = clearance
            async with pool.acquire() as conn:
                await conn.execute(
                    "SET LOCAL app.nexus_clearance = $1", clearance
                )

        await self.app(scope, receive, send)
