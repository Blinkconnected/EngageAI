"""Push transports. See ``docs/architecture/notifications.md``."""

from blinkengage.infrastructure.push.factory import build_push_sender

__all__ = ["build_push_sender"]
