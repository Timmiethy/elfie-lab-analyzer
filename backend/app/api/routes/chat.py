"""Secure chat proxy route: browser → backend → Qwen.

Why this exists: the earlier frontend called Qwen (DashScope) directly using a
`VITE_QWEN_API_KEY` baked into the Vite bundle — which means the key shipped to
every visitor. This route is the server-side replacement. The key lives only in
backend env (`ELFIE_QWEN_API_KEY`) and never crosses to the browser.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.auth import CurrentUserId
from app.schemas.chat import (
    MAX_HISTORY_CONTEXT_CHARS,
    ChatMessageIn,
    ChatRequest,
    ChatResponse,
)
from app.services.observability import get_current_correlation_id
from app.services.vlm_gateway import (
    VLMAPIError,
    VLMParsingError,
    generate_text_with_qwen,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-user token bucket: max N requests in WINDOW seconds. In-memory, per-process
# — good enough for a single-worker deployment; swap for Redis if we scale out.
_RATE_LIMIT_MAX = 20
_RATE_LIMIT_WINDOW_S = 300
_rate_log: dict[UUID, deque[float]] = {}

_SYSTEM_PROMPT = (
    "You are Elfie Coach, a friendly wellness companion for the Elfie Labs "
    "Analyzer app. You help the user understand their own uploaded lab report "
    "results in plain language. Rules you MUST follow:\n"
    "- Wellness support only. Never diagnose, prescribe, or change medication.\n"
    "- If asked medical-advice questions, redirect to a clinician.\n"
    "- Only discuss the lab data provided in the history context below; do not "
    "invent values.\n"
    "- Be concise. Use short paragraphs or bullet lists. Markdown allowed "
    "(**bold**, `- bullets`).\n"
    "- Reply in the same language the user writes in."
)


def _check_rate_limit(user_id: UUID) -> None:
    now = time.monotonic()
    bucket = _rate_log.setdefault(user_id, deque())
    # drop stale entries
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="chat_rate_limited",
        )
    bucket.append(now)


def _build_prompt(messages: list[ChatMessageIn], history_context: str | None) -> str:
    """Flatten the conversation into a single prompt string.

    Client-supplied `system` messages are DROPPED — the server owns the system
    prompt, so a malicious client cannot reprogram the assistant.
    """
    parts: list[str] = [_SYSTEM_PROMPT]
    if history_context:
        trimmed = history_context[:MAX_HISTORY_CONTEXT_CHARS]
        parts.append("\n## Lab history context (from the user's prior uploads)\n")
        parts.append(trimmed)
    parts.append("\n## Conversation\n")
    for m in messages:
        if m.role == "system":
            continue  # ignore client-side system injection
        speaker = "User" if m.role == "user" else "Assistant"
        parts.append(f"{speaker}: {m.content}")
    parts.append("Assistant:")
    return "\n".join(parts)


@router.post("/completions", response_model=ChatResponse)
async def chat_completions(
    user_id: CurrentUserId,
    payload: ChatRequest,
) -> ChatResponse:
    _check_rate_limit(user_id)

    prompt = _build_prompt(payload.messages, payload.history_context)

    correlation_id = get_current_correlation_id() or ""
    logger.info(
        "chat_request user_id=%s messages=%d prompt_chars=%d corr=%s",
        user_id,
        len(payload.messages),
        len(prompt),
        correlation_id,
    )

    try:
        reply = await generate_text_with_qwen(prompt)
    except VLMAPIError as exc:
        logger.warning("chat_upstream_error corr=%s err=%s", correlation_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="chat_upstream_error",
        ) from exc
    except VLMParsingError as exc:
        logger.warning("chat_parse_error corr=%s err=%s", correlation_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="chat_parse_error",
        ) from exc

    return ChatResponse(reply=reply.strip(), correlation_id=correlation_id)
