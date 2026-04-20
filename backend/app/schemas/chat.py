"""Pydantic schemas for the secure /api/chat proxy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Hard limits — protect upstream LLM cost + prevent prompt-stuffing abuse.
MAX_MESSAGES = 30
MAX_MESSAGE_CHARS = 4000
MAX_TOTAL_CHARS = 16000
MAX_HISTORY_CONTEXT_CHARS = 4000

ChatRole = Literal["user", "assistant", "system"]


class ChatMessageIn(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=MAX_MESSAGES)
    history_context: str | None = Field(default=None, max_length=MAX_HISTORY_CONTEXT_CHARS)

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, v: list[ChatMessageIn]) -> list[ChatMessageIn]:
        if v[-1].role != "user":
            raise ValueError("last_message_must_be_user")
        total = sum(len(m.content) for m in v)
        if total > MAX_TOTAL_CHARS:
            raise ValueError("messages_total_too_large")
        return v


class ChatResponse(BaseModel):
    reply: str
    correlation_id: str
