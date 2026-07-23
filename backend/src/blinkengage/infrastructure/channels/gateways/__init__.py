"""Import every concrete ``SmsGateway`` module here so
``@SmsGatewayRegistry.register(...)`` runs at import time — same pattern
as ``infrastructure.channels.providers``, one level down.
"""

from blinkengage.infrastructure.channels.gateways.twilio import TwilioGateway

__all__ = ["TwilioGateway"]
