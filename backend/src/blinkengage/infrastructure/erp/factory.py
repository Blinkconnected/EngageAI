"""Builds an ``ErpNextClient`` from a company's ``ErpConfig`` row —
decrypts credentials the same way ``ChannelProviderFactory`` builds a
``ChannelProvider`` from a ``ChannelConfig``. See
``docs/architecture/erp-integration.md``.
"""

from blinkengage.infrastructure.database.models.erp import ErpConfig
from blinkengage.infrastructure.erp.client import ErpNextClient


def build_erp_client(config: ErpConfig) -> ErpNextClient:
    return ErpNextClient(
        base_url=config.base_url,
        api_key=str(config.credentials.get("api_key", "")),
        api_secret=str(config.credentials.get("api_secret", "")),
    )
