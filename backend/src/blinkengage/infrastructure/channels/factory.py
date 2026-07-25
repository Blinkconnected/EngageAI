"""Builds a ``ChannelProvider`` instance from a ``ChannelConfig`` row —
looks up the class in ``ChannelRegistry`` by ``channel_type`` and passes
already-decrypted credentials (decryption happens transparently via
``EncryptedJSON`` when the row is loaded — see
``infrastructure.database.encrypted_json``). See
``docs/architecture/channels.md``.
"""

from typing import Any
from uuid import UUID, uuid4

# Import for its side effect: every @ChannelRegistry.register(...) decorator
# runs at import time. This used to be triggered only by api/v1/router.py,
# which the FastAPI process imports but no standalone Celery worker/beat
# process or async consumer script ever does — confirmed in production
# during Phase 1's live Docker verification, every one of
# channel_health_check_task, email_imap_poll_task and
# workflow_engine_consumer raised "Unknown channel type" for every single
# channel, since they all reach ChannelRegistry through this factory and
# none of them imported the providers package themselves. Importing it
# here instead — the one class whose entire job is "look up a registered
# provider" — makes correctness structural rather than depending on every
# current and future entrypoint remembering to add its own import.
import blinkengage.infrastructure.channels.providers  # noqa: F401
from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import AttachmentStorage
from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.domain.exceptions import InvalidChannelTypeError
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig


class ChannelProviderFactory:
    def __init__(
        self, *, realtime: RealtimeSignalPublisher, attachments: AttachmentStorage
    ) -> None:
        self._realtime = realtime
        self._attachments = attachments

    def build(self, config: ChannelConfig) -> ChannelProvider:
        return self._build(
            channel_type=config.channel_type,
            channel_config_id=config.id,
            company_id=config.company_id,
            credentials=config.credentials,
            webhook_secret=config.webhook_secret,
        )

    def build_ephemeral(
        self,
        *,
        channel_type: str,
        company_id: UUID,
        credentials: dict[str, Any],
        webhook_secret: str | None,
    ) -> ChannelProvider:
        """Builds a provider with no persisted ``ChannelConfig`` row — for
        validating credentials (``ChannelConfigService.
        test_connection_ephemeral``) before an operator has saved
        anything yet, the "Test Connection" step of the guided setup
        wizard (Phase 1: Channel Experience). A random id stands in for
        ``channel_config_id``; nothing this provider does in a health
        check keys off that id."""
        return self._build(
            channel_type=channel_type,
            channel_config_id=uuid4(),
            company_id=company_id,
            credentials=credentials,
            webhook_secret=webhook_secret,
        )

    def _build(
        self,
        *,
        channel_type: str,
        channel_config_id: UUID,
        company_id: UUID,
        credentials: dict[str, Any],
        webhook_secret: str | None,
    ) -> ChannelProvider:
        provider_cls = ChannelRegistry.get(channel_type)
        if provider_cls is None:
            raise InvalidChannelTypeError(channel_type)
        return provider_cls(
            channel_config_id=channel_config_id,
            company_id=company_id,
            credentials=credentials,
            webhook_secret=webhook_secret,
            realtime=self._realtime,
            attachments=self._attachments,
        )
