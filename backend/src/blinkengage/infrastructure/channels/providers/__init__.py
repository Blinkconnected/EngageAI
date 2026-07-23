"""Import every concrete ``ChannelProvider`` module here so
``@ChannelRegistry.register(...)`` runs at import time — mirrors
``core/celery_app.py``'s own ``include=[...]`` task-discovery pattern.
"""

from blinkengage.infrastructure.channels.providers.email import EmailProvider
from blinkengage.infrastructure.channels.providers.telegram import TelegramProvider
from blinkengage.infrastructure.channels.providers.web_chat import WebChatProvider
from blinkengage.infrastructure.channels.providers.whatsapp import WhatsAppProvider

__all__ = ["EmailProvider", "TelegramProvider", "WebChatProvider", "WhatsAppProvider"]
