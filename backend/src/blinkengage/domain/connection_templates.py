"""Connection templates — several channels from one consent.

A template is **data, not code**: an ordered set of channel types that share a
provider app, so approving once connects all of them. "Instagram + Messenger"
is one consent dialog and two channels; "Full Meta Suite" is one dialog and
three. Without templates the same customer approves three times and wonders
why, which is precisely the experience this milestone exists to remove.

Nothing here names a step or a screen. A template narrows *what* is being
connected; the flow still falls out of the connectors' capabilities exactly as
it does for a single channel. That is why adding a Slack template later needs
no code — only a row.

The single-channel entries are not redundant. A customer who wants only
WhatsApp should be asked for WhatsApp's permissions and nothing else: an
over-broad consent screen is the most common reason a customer abandons one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectionTemplate:
    """One offer in the channel picker."""

    key: str
    #: Which connectors this connects, in the order the picker groups them.
    channel_types: tuple[str, ...]
    #: Copy keys — the console translates; the server never sends prose.
    title_key: str
    description_key: str
    #: Shown first. Reserved for the offer most customers should take.
    recommended: bool = False

    @property
    def is_bundle(self) -> bool:
        return len(self.channel_types) > 1


TEMPLATES: tuple[ConnectionTemplate, ...] = (
    ConnectionTemplate(
        key="whatsapp_only",
        channel_types=("whatsapp",),
        title_key="connect.template.whatsappOnly.title",
        description_key="connect.template.whatsappOnly.description",
        recommended=True,
    ),
    ConnectionTemplate(
        key="instagram_messenger",
        channel_types=("instagram", "messenger"),
        title_key="connect.template.instagramMessenger.title",
        description_key="connect.template.instagramMessenger.description",
    ),
    ConnectionTemplate(
        key="full_meta_suite",
        channel_types=("whatsapp", "messenger", "instagram"),
        title_key="connect.template.fullMetaSuite.title",
        description_key="connect.template.fullMetaSuite.description",
    ),
)

_BY_KEY = {template.key: template for template in TEMPLATES}


def template_for(key: str) -> ConnectionTemplate | None:
    return _BY_KEY.get(key)


def templates_for_channel(channel_type: str) -> tuple[ConnectionTemplate, ...]:
    return tuple(t for t in TEMPLATES if channel_type in t.channel_types)


__all__ = [
    "TEMPLATES",
    "ConnectionTemplate",
    "template_for",
    "templates_for_channel",
]
