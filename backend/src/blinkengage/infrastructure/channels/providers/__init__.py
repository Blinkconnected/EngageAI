"""Import every concrete ``ChannelProvider`` module here so
``@ChannelRegistry.register(...)`` runs at import time — mirrors
``core/celery_app.py``'s own ``include=[...]`` task-discovery pattern.
"""

from blinkengage.infrastructure.channels.providers.email import EmailProvider
from blinkengage.infrastructure.channels.providers.instagram import InstagramProvider
from blinkengage.infrastructure.channels.providers.messenger import MessengerProvider
from blinkengage.infrastructure.channels.providers.sms import SmsProvider
from blinkengage.infrastructure.channels.providers.telegram import TelegramProvider
from blinkengage.infrastructure.channels.providers.web_chat import WebChatProvider
from blinkengage.infrastructure.channels.providers.whatsapp import WhatsAppProvider

__all__ = [
    "EmailProvider",
    "InstagramProvider",
    "MessengerProvider",
    "SmsProvider",
    "TelegramProvider",
    "WebChatProvider",
    "WhatsAppProvider",
]
