"""Import every concrete ``ChannelProvider`` module here so
``@ChannelRegistry.register(...)`` runs at import time — mirrors
``core/celery_app.py``'s own ``include=[...]`` task-discovery pattern.
"""

from blinkengage.infrastructure.channels.providers.web_chat import WebChatProvider

__all__ = ["WebChatProvider"]
