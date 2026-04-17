"""Supabase JWT authentication dependency for FastAPI."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.config import settings

_ALGORITHM = "HS256"
_MOCK_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
logger = logging.getLogger(__name__)


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

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        if settings.dev_auth_bypass:
            logger.warning("Dev auth bypass: missing header, using mock UUID.")
            return _MOCK_USER_ID
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_or_invalid_auth_header",
        )

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_not_configured",
        )

    token = auth_header[7:]
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_ALGORITHM],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        if settings.dev_auth_bypass:
            logger.warning("Dev auth bypass: token expired, using mock UUID.")
            return _MOCK_USER_ID
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token_expired",
        )
    except jwt.InvalidTokenError:
        if settings.dev_auth_bypass:
            logger.warning("Dev auth bypass: invalid token, using mock UUID.")
            return _MOCK_USER_ID
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

    try:
        return uuid.UUID(str(sub))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_subject",
        )


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
