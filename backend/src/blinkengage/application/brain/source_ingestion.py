"""Mail that teaches the Brain, taken in exactly once and only from named senders.

This service is everything the knowledge branch does in Phase 4A/4B/4F, and
the list of things it does **not** do is as load-bearing as the list it does:
no attachment is opened, no model is called, no ``KnowledgeRecord`` is written.
The only destination is a source row. 4C, 4D, 4E and 4G are not authorized, and
the structural guards in the test suite fail the build if that changes here.

It parses the raw MIME itself rather than reusing ``EmailChannelProvider``.
That looks like duplication and is not: the provider uploads every attachment
to object storage on its way to building an ``InboundMessage``, which is
precisely the extraction step this phase must not perform — and it discards the
``Authentication-Results`` headers that sender authorization depends on. Taking
the bytes directly keeps the customer path untouched and keeps the evidence.

Ordering is the durability guarantee: the row is committed **before** the
caller marks the message ``\\Seen``. A crash in between costs a redelivery, and
redelivery hits the unique constraint. Previously it cost the message.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.ingestion import ChannelPurpose, parse_channel_purpose
from blinkengage.domain.brain.sender_authorization import (
    AuthenticationResults,
    RejectionReason,
    authorize_sender,
    normalise_address,
    parse_authentication_results,
)
from blinkengage.domain.brain.source_safety import (
    contains_credential_material,
    to_plain_text,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.knowledge_source import (
    KnowledgeSenderAllowlistEntry,
    KnowledgeSourceMessage,
)

logger = get_logger(__name__)

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"

#: Where the company names the verifier whose Authentication-Results may be
#: believed. Stored on the channel's own credentials blob, which is already
#: encrypted at rest and already company-scoped.
AUTHSERV_ID_CREDENTIAL = "knowledge_authserv_id"


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """What happened to one message. ``duplicate`` is a success, not a failure."""

    stored: bool
    duplicate: bool = False
    rejection_reason: RejectionReason | None = None
    source_id: UUID | None = None

    @property
    def accepted(self) -> bool:
        return self.stored and self.rejection_reason is None


@dataclass(frozen=True, slots=True)
class _Parsed:
    message_id: str
    content_hash: str
    sender: str
    recipients: str | None
    subject: str | None
    received_at: datetime | None
    raw_body: str | None
    plain_body: str | None
    attachment_count: int
    authentication_headers: tuple[str, ...]


class KnowledgeSourceIngestionService:
    """The knowledge branch of inbound mail."""

    def __init__(self, *, session: AsyncSession, events: DomainEventPublisher) -> None:
        self._session = session
        self._events = events

    async def ingest(self, *, config: ChannelConfig, raw: bytes) -> IngestionOutcome:
        """Take one raw message in, or record why it was refused.

        Never raises for a bad message: a malformed body, an unauthorised
        sender and a credential-bearing attachment are all *outcomes*, each
        recorded as a row so an operator can see that somebody tried.
        """
        # Purpose first, and it fails closed. Reaching here with anything but
        # KNOWLEDGE_INGESTION means the caller routed wrongly, and continuing
        # would write a source row for a support mailbox.
        purpose = parse_channel_purpose(config.purpose)
        if purpose is not ChannelPurpose.KNOWLEDGE_INGESTION:
            return await self._reject_without_body(
                config=config, reason=RejectionReason.INVALID_CHANNEL_PURPOSE
            )

        try:
            parsed = _parse(raw)
        except Exception:
            logger.warning(
                "knowledge_source_unparseable",
                company_id=str(config.company_id),
                channel_config_id=str(config.id),
                exc_info=True,
            )
            return await self._reject_without_body(
                config=config, reason=RejectionReason.MALFORMED_MESSAGE
            )

        credentials: dict[str, Any] = config.credentials or {}
        results = parse_authentication_results(
            parsed.authentication_headers,
            trusted_authserv_id=credentials.get(AUTHSERV_ID_CREDENTIAL),
        )

        allowlisted = await self._is_allowlisted(company_id=config.company_id, sender=parsed.sender)
        decision = authorize_sender(sender=parsed.sender, allowlisted=allowlisted, results=results)

        reason = decision.reason
        if reason is None and contains_credential_material(
            parsed.raw_body, parsed.plain_body, parsed.subject
        ):
            # Refused, not redacted. A pattern that misses leaves the secret in
            # a row retrieval can read, and "we filtered it" is unverifiable
            # afterwards; the absence of the row is not.
            reason = RejectionReason.CREDENTIAL_MATERIAL

        return await self._store(config=config, parsed=parsed, results=results, reason=reason)

    async def _is_allowlisted(self, *, company_id: UUID, sender: str) -> bool:
        """Company-scoped, address-exact, enabled-only.

        No domain rule. "Anyone at the company domain" is what lets a spoofed
        executive address and a departed employee both write pricing.
        """
        normalized = normalise_address(sender)
        if not normalized:
            return False
        found = await self._session.execute(
            select(KnowledgeSenderAllowlistEntry.id).where(
                KnowledgeSenderAllowlistEntry.company_id == company_id,
                KnowledgeSenderAllowlistEntry.normalized_email == normalized,
                KnowledgeSenderAllowlistEntry.enabled.is_(True),
            )
        )
        return found.first() is not None

    async def _store(
        self,
        *,
        config: ChannelConfig,
        parsed: _Parsed,
        results: AuthenticationResults,
        reason: RejectionReason | None,
    ) -> IngestionOutcome:
        accepted = reason is None
        # Read before the flush. A rollback expires every instance in the
        # session, so touching ``config.company_id`` afterwards would trigger
        # a lazy refresh — which is IO, from a place that cannot await it.
        company_id = config.company_id
        channel_config_id = config.id

        row = KnowledgeSourceMessage(
            company_id=company_id,
            channel_config_id=channel_config_id,
            message_id=parsed.message_id,
            content_hash=parsed.content_hash,
            sender=parsed.sender[:320],
            recipients=parsed.recipients,
            subject=parsed.subject,
            received_at=parsed.received_at,
            # A rejected message keeps its envelope and its reason and loses
            # its content: there is no reason to retain the body of something
            # nobody was authorised to send, and a credential rejection that
            # stored the credential would defeat itself.
            raw_body=parsed.raw_body if accepted else None,
            plain_body=parsed.plain_body if accepted else None,
            status=STATUS_ACCEPTED if accepted else STATUS_REJECTED,
            rejection_reason=reason.value if reason else None,
            attachment_count=parsed.attachment_count,
            authentication_authserv_id=results.authserv_id,
            authentication_summary=(f"spf={results.spf};dkim={results.dkim};dmarc={results.dmarc}"),
        )
        self._session.add(row)
        try:
            # The constraint decides, not a prior SELECT: two pollers racing on
            # one message both read "absent" before either writes.
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            await self._publish(
                company_id=company_id,
                channel_config_id=channel_config_id,
                event_type="knowledge.source.duplicate",
                parsed=parsed,
                reason=None,
            )
            logger.info(
                "knowledge_source_duplicate",
                company_id=str(company_id),
                message_id=parsed.message_id,
            )
            return IngestionOutcome(stored=False, duplicate=True)

        source_id = row.id
        await self._publish(
            company_id=company_id,
            channel_config_id=channel_config_id,
            event_type=("knowledge.source.received" if accepted else "knowledge.source.rejected"),
            parsed=parsed,
            reason=reason,
            source_id=source_id,
        )
        return IngestionOutcome(stored=True, rejection_reason=reason, source_id=source_id)

    async def _reject_without_body(
        self, *, config: ChannelConfig, reason: RejectionReason
    ) -> IngestionOutcome:
        """A refusal that never got far enough to have a parsed identity."""
        logger.warning(
            "knowledge_source_rejected",
            company_id=str(config.company_id),
            channel_config_id=str(config.id),
            reason=reason.value,
        )
        await self._events.publish(
            DomainEvent(
                event_type="knowledge.source.rejected",
                company_id=config.company_id,
                aggregate_type="knowledge_source_message",
                aggregate_id=None,
                payload={
                    "channel_config_id": str(config.id),
                    "rejection_reason": reason.value,
                },
            )
        )
        return IngestionOutcome(stored=False, rejection_reason=reason)

    async def _publish(
        self,
        *,
        company_id: UUID,
        channel_config_id: UUID,
        event_type: str,
        parsed: _Parsed,
        reason: RejectionReason | None,
        source_id: UUID | None = None,
    ) -> None:
        """On the existing outbox. No parallel event mechanism.

        The payload carries the envelope and never the body: an event is read
        by consumers and printed in logs, and a company's pricing does not
        belong in either.
        """
        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=company_id,
                aggregate_type="knowledge_source_message",
                aggregate_id=source_id,
                payload={
                    "channel_config_id": str(channel_config_id),
                    "message_id": parsed.message_id,
                    "content_hash": parsed.content_hash,
                    "sender": parsed.sender,
                    "attachment_count": parsed.attachment_count,
                    "rejection_reason": reason.value if reason else None,
                },
            )
        )


def _parse(raw: bytes) -> _Parsed:
    """Raw bytes to an envelope, a body and the headers that authorise it.

    Attachments are **counted, never opened**: Phase 4C is not authorized, and
    a decode here would be exactly the extraction step this phase excludes.
    """
    message: EmailMessage = BytesParser(EmailMessage, policy=policy.default).parsebytes(raw)

    message_id = str(message.get("Message-ID") or "").strip()
    content_hash = hashlib.sha256(raw).hexdigest()
    if not message_id:
        # No Message-ID: the content hash alone becomes the identity. A random
        # substitute would make every redelivery a new document.
        message_id = f"<sha256:{content_hash}>"

    sender = normalise_address(str(message.get("From") or ""))
    if "<" in str(message.get("From") or ""):
        _, _, bracketed = str(message.get("From")).partition("<")
        sender = normalise_address(bracketed.partition(">")[0])

    received_at: datetime | None = None
    date_header = message.get("Date")
    if date_header is not None:
        try:
            parsed_date = parsedate_to_datetime(str(date_header))
            received_at = (
                parsed_date if parsed_date.tzinfo is not None else parsed_date.replace(tzinfo=UTC)
            )
        except (TypeError, ValueError):
            received_at = None

    raw_body: str | None = None
    html_body: str | None = None
    attachment_count = 0
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            attachment_count += 1
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and raw_body is None:
            content = part.get_content()
            raw_body = content if isinstance(content, str) else None
        elif content_type == "text/html" and html_body is None:
            content = part.get_content()
            html_body = content if isinstance(content, str) else None

    if raw_body is None and html_body is not None:
        raw_body = html_body
    plain_body = to_plain_text(html_body) if html_body is not None else raw_body

    return _Parsed(
        message_id=message_id[:998],
        content_hash=content_hash,
        sender=sender,
        recipients=str(message.get("To") or "") or None,
        subject=str(message.get("Subject") or "") or None,
        received_at=received_at,
        raw_body=raw_body,
        plain_body=plain_body,
        attachment_count=attachment_count,
        authentication_headers=tuple(
            str(header) for header in message.get_all("Authentication-Results", [])
        ),
    )


__all__ = [
    "AUTHSERV_ID_CREDENTIAL",
    "STATUS_ACCEPTED",
    "STATUS_REJECTED",
    "IngestionOutcome",
    "KnowledgeSourceIngestionService",
]
