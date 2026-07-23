from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class TypingFrameIn(BaseModel):
    """The only client->server frame the agent WebSocket gateway accepts
    today — see ``docs/architecture/notifications.md``. Forwarded to
    ``ConversationService.send_typing_indicator``, which finally invokes
    the ``ChannelProvider.typing_indicator`` method every provider has
    implemented since M11/M12 but nothing had ever called."""

    type: Literal["typing"] = "typing"
    conversation_id: UUID
    is_typing: bool
