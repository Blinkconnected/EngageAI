"""``MessengerProvider`` — Facebook Messenger Platform. See
``docs/architecture/messenger-instagram.md``.

Credentials: ``access_token`` (Page access token), ``page_id``.
"""

from blinkengage.infrastructure.channels.providers._meta_messaging import MetaMessagingProvider
from blinkengage.infrastructure.channels.registry import ChannelRegistry


@ChannelRegistry.register("messenger")
class MessengerProvider(MetaMessagingProvider):
    _recipient_credential_key = "page_id"
