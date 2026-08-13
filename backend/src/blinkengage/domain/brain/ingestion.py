"""Mail that teaches the platform, kept apart from mail that asks it something.

Two rules, and Phase 1 builds only the boundary that expresses them.

**A knowledge mailbox never creates a customer.** Today every inbound message
reaches ``conversation_ingest_consumer``, which resolves or creates a
``Customer`` from the sender. Pointing ``ai@company.com`` at that would
manufacture customer records for the company's own finance team and open
support conversations about price lists. ``ChannelConfig`` carries no notion of
purpose, so the branch has nowhere to happen — :class:`ChannelPurpose` is that
notion, and the column that carries it lands in a later phase.

**Identity is durable, and it is not ``\\Seen``.** The IMAP poll marks each
message ``\\Seen`` inside the fetch loop, on the IMAP thread, before anything
is persisted; its docstring calls that "the idempotency mechanism … no separate
cursor table needed". For conversation ingestion the cost of a crash between
those two points is bounded, because a customer resends. For knowledge it is a
price list that silently never arrived and that nothing anywhere records the
existence of. :func:`ingestion_identity` is the key that has to be written
*before* the message is acknowledged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class ChannelPurpose(StrEnum):
    """What a channel configuration is *for*.

    Not the same question as ``channel_type``. Two IMAP mailboxes are both
    ``email``; one is a support inbox and the other teaches the Brain, and
    routing them identically is the defect this enum exists to make
    impossible.
    """

    #: The existing behaviour, and the default for every configuration that
    #: predates this enum. Inbound becomes a conversation.
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    #: Inbound is evidence for the Brain. Never a customer, never a
    #: conversation, never an automatic reply.
    KNOWLEDGE_INGESTION = "KNOWLEDGE_INGESTION"
    #: Configured for something that is neither. Routed nowhere rather than
    #: defaulted into support, so that adding a purpose is a deliberate act.
    OTHER = "OTHER"


class IngestionRoute(StrEnum):
    """Where an inbound message goes."""

    CONVERSATION = "CONVERSATION"
    KNOWLEDGE = "KNOWLEDGE"
    #: Rejected and audited. Never parsed, never indexed, never guessed at.
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class InboundEnvelope:
    """What is known about a message before any of its content is read.

    Company resolution precedes parsing: mail resolves to exactly one company
    by the ``channel_config`` it arrived through, and mail that cannot is
    rejected. Company resolution *is* the tenant boundary, so it has to happen
    before anything reads the body — a document that has been parsed has
    already been trusted.
    """

    company_id: uuid.UUID
    channel_config_id: uuid.UUID
    purpose: ChannelPurpose
    #: RFC 5322 ``Message-ID``. Absent or forged on some senders, which is why
    #: it is not the identity on its own.
    message_id: str | None = None
    #: Hash of the raw message. The fallback when ``Message-ID`` is missing,
    #: and the tiebreaker when it is reused — some bulk senders reuse one
    #: across genuinely different mail.
    content_hash: str | None = None


class UnidentifiableMessageError(Exception):
    """Neither a ``Message-ID`` nor a content hash was available.

    Raised rather than defaulted to a random key. A random key makes every
    redelivery a new document, which for a price list means publishing the same
    change repeatedly — the failure the identity exists to prevent.
    """


def creates_customer(purpose: ChannelPurpose) -> bool:
    """Does inbound mail on this purpose resolve to a customer?

    Only support does. Stated as a function rather than an ``if`` at the call
    site so the guard test has something to bind to, and so adding a purpose
    forces a decision here instead of falling through to the existing
    behaviour.
    """
    return purpose is ChannelPurpose.CUSTOMER_SUPPORT


def route_inbound(envelope: InboundEnvelope) -> IngestionRoute:
    """Which pipeline this message belongs to."""
    match envelope.purpose:
        case ChannelPurpose.CUSTOMER_SUPPORT:
            return IngestionRoute.CONVERSATION
        case ChannelPurpose.KNOWLEDGE_INGESTION:
            return IngestionRoute.KNOWLEDGE
        case ChannelPurpose.OTHER:
            return IngestionRoute.REJECT


def ingestion_identity(envelope: InboundEnvelope) -> str:
    """The durable key for "have we already taken this message in?".

    Scoped by company first: the same ``Message-ID`` arriving at two companies'
    mailboxes is two documents, and a global key would let one company's
    ingestion suppress another's.

    Both identifiers are included when both exist. ``Message-ID`` alone is
    forgeable and occasionally reused; a content hash alone makes a resent
    identical message look like the same one, which is usually right and is not
    always — the pair is what survives both.
    """
    parts = [str(envelope.company_id), str(envelope.channel_config_id)]
    message_id = (envelope.message_id or "").strip()
    content_hash = (envelope.content_hash or "").strip()

    if not message_id and not content_hash:
        raise UnidentifiableMessageError("an ingested message needs a Message-ID or a content hash")

    parts.append(message_id or "-")
    parts.append(content_hash or "-")
    return "|".join(parts)


__all__ = [
    "ChannelPurpose",
    "InboundEnvelope",
    "IngestionRoute",
    "UnidentifiableMessageError",
    "creates_customer",
    "ingestion_identity",
    "route_inbound",
]
