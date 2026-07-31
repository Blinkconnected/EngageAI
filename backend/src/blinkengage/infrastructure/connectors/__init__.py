"""Every connector this build knows how to connect.

The imports below are the registry's discovery mechanism: each module runs a
``@ConnectorRegistry.register`` decorator at import time, and a connector
nobody imports is a connector that silently does not exist. An explicit list
rather than a filesystem scan, deliberately — a connector that fails to import
should break the build loudly, because its absence from the catalog looks to a
customer exactly like a channel Blink Engage does not support.

Adding a channel is: one module here, one line below. Nothing else in the
product changes — not the wizard, not the API, not the console. That is the
whole claim of the connector framework, and this file is where it is either
true or it isn't.

Ordered alphabetically rather than by importance so a merge conflict here is
trivial to resolve, and so nobody has to decide what "importance" means.
"""

from blinkengage.infrastructure.connectors import (  # noqa: F401 - registration side effect
    email,
    meta,
    sms,
    telegram,
    web_chat,
)
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

__all__ = ["ConnectorRegistry"]
