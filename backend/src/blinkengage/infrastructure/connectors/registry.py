"""Which connectors this build knows about.

Mirrors ``infrastructure.channels.registry.ChannelRegistry`` deliberately —
same decorator, same explicit-import discovery, same duplicate check — so
somebody adding a channel meets one pattern twice rather than two patterns
once. The transport registry answers "how do I talk to WhatsApp"; this one
answers "how does a customer connect it".

Registration is by decorator and discovery is an explicit import list in
``__init__``, not a filesystem scan: a connector that fails to import should
break the build loudly rather than vanish from the catalog, where its absence
would look to a customer exactly like a channel we do not support.
"""

from __future__ import annotations

from collections.abc import Callable

from blinkengage.domain.connector import Connector, DeploymentContext
from blinkengage.domain.connectors import ConnectorProfile


class ConnectorRegistry:
    """Process-wide ``channel_type`` → connector instance."""

    _connectors: dict[str, Connector] = {}

    @classmethod
    def register(cls, channel_type: str) -> Callable[[type[Connector]], type[Connector]]:
        def decorate(connector_cls: type[Connector]) -> type[Connector]:
            existing = cls._connectors.get(channel_type)
            if existing is not None and type(existing) is not connector_cls:
                raise ValueError(
                    f"Two connectors claim '{channel_type}': "
                    f"{type(existing).__name__} and {connector_cls.__name__}. "
                    "A channel type has exactly one connection lifecycle."
                )
            connector_cls.channel_type = channel_type
            cls._connectors[channel_type] = connector_cls()
            return connector_cls

        return decorate

    @classmethod
    def get(cls, channel_type: str) -> Connector | None:
        return cls._connectors.get(channel_type)

    @classmethod
    def all(cls) -> tuple[Connector, ...]:
        """Every connector, in a stable order.

        Sorted by channel type rather than by registration order so the
        catalog — and therefore the channel picker — does not silently
        reorder itself when an import moves.
        """
        return tuple(cls._connectors[key] for key in sorted(cls._connectors))

    @classmethod
    def catalog(cls, context: DeploymentContext) -> tuple[ConnectorProfile, ...]:
        """Every connector resolved against this installation.

        The one call the API needs, and the reason the console can render a
        channel picker without knowing what a channel is.
        """
        return tuple(connector.resolve(context) for connector in cls.all())


__all__ = ["ConnectorRegistry"]
