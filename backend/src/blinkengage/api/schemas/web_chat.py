"""Web Chat REST + WebSocket frame schemas — the "chat widget contract"
documented in ``docs/architecture/web-chat.md``.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator


class CreateChatSessionRequest(BaseModel):
    session_token: str | None = None


class CreateChatSessionResponse(BaseModel):
    session_token: str
    customer_id: UUID


class WidgetMessageIn(BaseModel):
    """One inbound WebSocket frame from the chat widget — either a
    message (``type="message"``, the default — a widget client that
    predates this ``type`` field entirely, sending no ``type`` key at
    all, is still valid) or a customer-is-typing signal (``type=
    "typing"``, ``is_typing``). See ``docs/architecture/web-chat.md``'s
    "chat widget contract" for the full protocol."""

    type: Literal["message", "typing"] = "message"
    body: str | None = None
    reply_to_external_message_id: str | None = None
    is_typing: bool | None = None

    @model_validator(mode="after")
    def _check_message_has_body(self) -> "WidgetMessageIn":
        if self.type == "message" and self.body is None:
            raise ValueError("a 'message' frame requires a body")
        if self.type == "typing" and self.is_typing is None:
            raise ValueError("a 'typing' frame requires is_typing")
        return self


class WidgetMessageOut(BaseModel):
    """One outbound WebSocket frame pushed to the chat widget."""

    type: str
    body: str | None = None
    is_typing: bool | None = None
    external_message_id: str | None = None
    reply_to_external_message_id: str | None = None
