"""Process-wide registry mapping ``channel_type`` -> ``ChannelProvider``
subclass. Discovery is one explicit import list
(``infrastructure.channels.providers``), mirroring
``core/celery_app.py``'s own ``include=[...]`` task-discovery pattern —
explicit over magic, matching this codebase's established style. See
``docs/architecture/channels.md``.
"""

from collections.abc import Callable

from blinkengage.domain.channel_provider import ChannelProvider


class ChannelRegistry:
    _providers: dict[str, type[ChannelProvider]] = {}

    @classmethod
    def register(
        cls, channel_type: str
    ) -> Callable[[type[ChannelProvider]], type[ChannelProvider]]:
        """``@ChannelRegistry.register("whatsapp")`` on a concrete
        ``ChannelProvider`` subclass. Adding provider #50 ten years from
        now is one new class + one line like this — nothing else in the
        codebase changes."""

        def _decorator(provider_cls: type[ChannelProvider]) -> type[ChannelProvider]:
            existing = cls._providers.get(channel_type)
            if existing is not None and existing is not provider_cls:
                raise ValueError(
                    f"Channel type {channel_type!r} is already registered to {existing!r}"
                )
            provider_cls.channel_type = channel_type
            cls._providers[channel_type] = provider_cls
            return provider_cls

        return _decorator

    @classmethod
    def get(cls, channel_type: str) -> type[ChannelProvider] | None:
        return cls._providers.get(channel_type)

    @classmethod
    def known_channel_types(cls) -> frozenset[str]:
        return frozenset(cls._providers.keys())
