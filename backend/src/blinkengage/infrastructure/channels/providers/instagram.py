"""``InstagramProvider`` — Instagram Messaging API (the same Messenger
Platform infrastructure, scoped to an Instagram Business Account). See
``docs/architecture/messenger-instagram.md``.

Credentials: ``access_token`` (the Instagram-connected Page's access
token), ``instagram_id`` (Instagram Business Account id).
"""

from blinkengage.infrastructure.channels.providers._meta_messaging import MetaMessagingProvider
from blinkengage.infrastructure.channels.registry import ChannelRegistry


@ChannelRegistry.register("instagram")
class InstagramProvider(MetaMessagingProvider):
    _recipient_credential_key = "instagram_id"
