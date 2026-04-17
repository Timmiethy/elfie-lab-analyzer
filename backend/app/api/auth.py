"""Supabase JWT authentication dependency for FastAPI."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.config import settings

_ALGORITHM = "HS256"


def _get_token_from_header(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_or_invalid_auth_header",
        )
    return auth_header[7:]


def get_current_user_id(request: Request) -> uuid.UUID:
    """Validate Supabase JWT and return user UUID from the ``sub`` claim."""

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_not_configured",
        )

    token = _get_token_from_header(request)
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_ALGORITHM],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token_expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_subject",
        )

    return uuid.UUID(sub)


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
