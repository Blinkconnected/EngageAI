"""Builds a ``ChannelProvider`` instance from a ``ChannelConfig`` row —
looks up the class in ``ChannelRegistry`` by ``channel_type`` and passes
already-decrypted credentials (decryption happens transparently via
``EncryptedJSON`` when the row is loaded — see
``infrastructure.database.encrypted_json``). See
``docs/architecture/channels.md``.
"""

from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.domain.exceptions import InvalidChannelTypeError
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig


class ChannelProviderFactory:
    def __init__(self, *, realtime: RealtimeSignalPublisher) -> None:
        self._realtime = realtime

    def build(self, config: ChannelConfig) -> ChannelProvider:
        provider_cls = ChannelRegistry.get(config.channel_type)
        if provider_cls is None:
            raise InvalidChannelTypeError(config.channel_type)
        return provider_cls(
            channel_config_id=config.id,
            company_id=config.company_id,
            credentials=config.credentials,
            webhook_secret=config.webhook_secret,
            realtime=self._realtime,
        )
