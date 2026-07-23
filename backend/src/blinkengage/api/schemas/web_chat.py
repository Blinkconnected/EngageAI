"""Web Chat REST + WebSocket frame schemas — the "chat widget contract"
documented in ``docs/architecture/web-chat.md``.
"""

from uuid import UUID

from pydantic import BaseModel


class CreateChatSessionRequest(BaseModel):
    session_token: str | None = None


class CreateChatSessionResponse(BaseModel):
    session_token: str
    customer_id: UUID


class WidgetMessageIn(BaseModel):
    """One inbound WebSocket frame from the chat widget."""

    body: str
    reply_to_external_message_id: str | None = None


class WidgetMessageOut(BaseModel):
    """One outbound WebSocket frame pushed to the chat widget."""

    type: str
    body: str | None = None
    is_typing: bool | None = None
    external_message_id: str | None = None
    reply_to_external_message_id: str | None = None
