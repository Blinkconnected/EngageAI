"""Conversation ORM model. See ``docs/architecture/conversations.md``.

``external_thread_id`` is how the (channel-agnostic) conversation engine
recognizes "this inbound message belongs to an existing conversation" —
unique per ``channel_config_id`` among active rows, the same partial-
unique-index pattern ``Department.name``/``Customer.email`` already
establish (see ``docs/architecture/core-crm.md`` decision #1).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.lifecycle import ConversationStatus as LifecycleStatus
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

#: Re-exported from ``domain/lifecycle.py``, which owns the lifecycle and its
#: transitions. Kept as a name here because every existing import points at
#: it, and moving those in the same change as splitting four statuses into
#: eight would make the diff impossible to review.
ConversationStatus = LifecycleStatus


class ConversationPriority(StrEnum):
    """A manual/system-set triage signal, independent of SLA policy (SLA
    targets stay purely queue-driven — see ``docs/architecture/sla.md``
    — priority never changes a policy's response/resolution targets).
    Ordered low-to-high so callers that need a comparable urgency (e.g.
    Inbox default sort) can do ``list(ConversationPriority).index(p)``
    rather than hand-rolling a second ranking table."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversations_channel_config_thread",
            "channel_config_id",
            "external_thread_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
        ),
        # M28 (see docs/architecture/performance.md): ConversationRepository
        # .list_for_company filters on company_id and sorts by
        # (last_message_at desc, created_at desc) on every page of every
        # conversation list request — the single-column company_id index
        # alone forces a separate in-memory sort of every matching row
        # before LIMIT can be applied (confirmed via EXPLAIN ANALYZE),
        # which gets expensive at real conversation volume per company.
        # A partial index (only non-deleted rows, matching the query's own
        # WHERE clause) storing rows pre-sorted lets Postgres satisfy the
        # whole query — filter, sort, and LIMIT — from the index alone.
        #
        # Deliberately plain ``DESC`` here (no ``NULLS LAST``): SQLite
        # (test-only, via this model's own ``Base.metadata.create_all``)
        # doesn't support ``NULLS LAST`` in an index definition at all —
        # confirmed empirically, not merely undocumented. The real
        # Postgres schema (governed by the migration, not this model —
        # same "per-dialect index nuance" precedent as
        # ``postgresql_where``/``sqlite_where`` below) uses the more
        # precise ``DESC NULLS LAST`` to exactly match the query's ORDER
        # BY and avoid Postgres's own residual sort step.
        # The AI pickup sweep's query: conversations AI is waiting to take,
        # soonest first. Partial, because the column is null for almost
        # every row in the table — a conversation is only in this index for
        # the few seconds between arriving and being settled either way.
        Index(
            "ix_conversations_ai_pickup",
            "ai_pickup_eligible_at",
            postgresql_where=text("ai_pickup_eligible_at IS NOT NULL"),
            sqlite_where=text("ai_pickup_eligible_at IS NOT NULL"),
        ),
        Index(
            "ix_conversations_company_last_message",
            "company_id",
            text("last_message_at DESC"),
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_thread_id: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, native_enum=False, length=20),
        nullable=False,
        # NEW, not WAITING: a conversation exists for the instant between
        # its first message being stored and routing placing it, and a row
        # found sitting in NEW is a routing failure worth being able to
        # find. Ingest sets WAITING (or IN_PROGRESS) immediately after.
        default=ConversationStatus.NEW,
    )
    # Inbox triage signal (see docs/architecture/queues-routing.md) —
    # deliberately independent of Queue/SlaPolicy: it never changes an
    # SLA policy's response/resolution targets, it only drives default
    # sort order and visual urgency in the Inbox. Defaults to NORMAL so
    # every pre-existing and newly-ingested conversation has a
    # meaningful value with no backfill migration needed.
    priority: Mapped[ConversationPriority] = mapped_column(
        Enum(ConversationPriority, native_enum=False, length=20),
        nullable=False,
        default=ConversationPriority.NORMAL,
        # "NORMAL" (uppercase) — Enum(native_enum=False) stores a
        # StrEnum member's NAME, not its lowercase .value (see the
        # migration's own comment; confirmed against how
        # conversations.status already stores "OPEN", not "open").
        server_default=ConversationPriority.NORMAL.name,
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None, index=True
    )
    # Set when a transfer targets a department rather than a specific
    # agent (see ConversationService.transfer(), Sprint 2 "Pilot
    # Feedback & UX Improvements" Item 4) — the conversation is then
    # unassigned (assigned_agent_id=None) and "owned" by the department's
    # shared pool until some agent in it picks it up. Independent of
    # Queue.department_id (an organizational label on a queue, not an
    # eligibility filter — see docs/architecture/queues-routing.md):
    # this column is the conversation's own current routing target, set
    # directly by a transfer, not derived through a queue.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None, index=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- Customer Activity (see docs/architecture/customer-activity.md) ---
    #
    # A projection of the `messages` table, exactly as `assigned_agent_id` is a
    # projection of `conversation_ownership`. Written by
    # `CustomerActivityProjector` and nothing else — see
    # `test_customer_activity_is_the_only_writer.py`, which fails when a new
    # path assigns one of these.
    #
    # Here rather than in a side table because the Inbox reads them on every
    # row of every page and the AI sweep filters on them installation-wide; a
    # join for that is a join that gets denormalised back within a milestone.
    #
    # Note `last_message_at` above is a *different* fact: it moves for outbound
    # messages too, which is precisely why it could never answer "is a customer
    # waiting".
    #: The **oldest** currently-unanswered inbound message. NULL when nobody is
    #: waiting. Live wait = now - this; never stored, because a duration column
    #: is wrong the moment after it is written.
    awaiting_reply_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    #: The **newest** inbound message. Deliberately not collapsed with the one
    #: above: a customer who wrote four times in a minute has been waiting
    #: since the first, and that is the figure people escalate about.
    last_customer_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    #: No FKs on the three ids: `messages` is soft-deleted and
    #: retention-pruned, and a FK would either block a legitimate prune or
    #: cascade a NULL over the record of who last spoke.
    last_customer_message_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    last_agent_message_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    last_ai_message_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    unanswered_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: The settled wait — how long the customer waited for the answer they
    #: actually received. History, immutable once written.
    last_wait_duration_seconds: Mapped[int | None] = mapped_column(Integer, default=None)

    # --- M14: queues, assignment, SLA (see docs/architecture/queues-routing.md) ---
    queue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="SET NULL"), default=None, index=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_first_response_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_resolution_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # SLA Builder (see docs/architecture/sla.md): set once a conversation
    # crosses its policy's warning_threshold_percent, *before* it actually
    # breaches — same idempotency-guard role as the *_breached_at columns
    # above (SlaMonitorService checks these are still None before
    # publishing conversation.sla_warning, so a warning is only ever
    # published once per conversation per breach type, same as a breach).
    sla_first_response_warned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_resolution_warned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # --- Queue Operations: pickup/release/metrics (see queues-routing.md
    # decisions 6-10). queue_id itself is never cleared once set (a
    # permanent "which queue routed this" tag — see live_queue_depth); these
    # three columns track *when* the conversation entered its current
    # unowned wait, was last claimed, and was last closed, since that
    # cannot be recovered from queue_id/assigned_agent_id's current values
    # alone once a conversation cycles through pick/release more than once.
    #: When AI Autopilot may take this conversation, if nobody else has.
    #:
    #: Materialised rather than derived from ``queue_entered_at`` plus the
    #: service's delay, so the sweep is one indexed range scan instead of a
    #: join to a version table per row — the same reasoning as
    #: ``ConversationSlaClock.due_at``.
    #:
    #: ``None`` means AI is not waiting on this conversation: either it was
    #: never eligible, or it has already been taken, or the sweep has
    #: settled it one way or the other. A row keeps its value while a human
    #: holds the conversation, deliberately — that is how the sweep learns
    #: an agent got there first and can say so.
    ai_pickup_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    queue_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set exactly once, the first time ``ConversationRepository.claim()``
    # ever succeeds for this conversation, and never cleared afterwards —
    # unlike ``picked_up_at`` above, which tracks the *current*/most-recent
    # claim and IS cleared back to ``None`` by ``ConversationService
    # .release()``. ``ReportingRepository.queue_metrics()``'s
    # ``abandoned_count_24h`` heuristic needs a "was this conversation
    # EVER handled by anyone, at any point in its history" signal that
    # survives a pick() -> release() -> close() cycle, which
    # ``picked_up_at`` alone can no longer provide now that release()
    # clears it.
    first_picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Post-resolution CSAT (see docs/architecture/reports-analytics.md's
    # "Customer Satisfaction" section): set the first time
    # csat_dispatch_consumer sends this conversation's survey link, so a
    # later reopen/re-resolve cycle (RESOLVED -> OPEN -> RESOLVED again,
    # allowed by _ALLOWED_TRANSITIONS) — or an at-least-once redelivery of
    # the same conversation.resolved event — doesn't send a second survey
    # for the same conversation.
    csat_survey_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # --- AI Autopilot (see docs/architecture/ai-engine.md) ---
    # True while the AI, not a human, is responsible for replying to this
    # conversation — set instead of auto-assigning a human agent, only
    # for a queue with ``Queue.autopilot_enabled`` (see
    # conversation_ingest_consumer.py's ``_route_and_assign``). Cleared
    # back to False the moment a human takes over, by any of the three
    # existing paths that ever set ``assigned_agent_id``
    # (``ConversationRepository.claim()`` i.e. ``pick()``,
    # ``ConversationService.transfer()``, ``ConversationService.update()``)
    # — a plain live-state flag, not an idempotency marker, since unlike
    # every ``*_at`` column above it can legitimately flip back and forth
    # (e.g. a human later releases it and it could be re-enabled).
    autopilot_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Idempotency guard for the per-inbound-message autopilot decision
    # (reply automatically vs. hand off) — the id of the last inbound
    # Message ``ai_autopilot_consumer`` has already acted on. Guards
    # against both a redelivery of the same ``message.persisted`` event
    # (at-least-once delivery) causing a duplicate auto-reply or a
    # duplicate handoff notification.
    autopilot_last_handled_message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), default=None
    )
