"""The Service Directory: services, their frozen versions, and runtime lanes.

See ``docs/architecture/execution-context.md`` and
``docs/architecture/queue-architecture.md``.

Three ideas, and the table layout follows them exactly:

**A service has an identity and a configuration, and they change at different
rates.** ``services`` is the identity — it is edited, renamed, archived, and
there is exactly one row per service. ``service_versions`` is the
configuration, and it is **append-only**: editing a service mints a new
version rather than overwriting the old one, because thousands of running
conversations are bound to what it said when they started.

**A customer's routing-relevant attributes are versioned the same way**, but
minted from a fingerprint rather than on every edit — see
``domain/customer_context.py`` for why a customer record changing constantly
makes the naive approach useless.

**A logical queue is not a runtime lane.** ``queues`` (the existing table) is
what an administrator names and assigns agents to; ``runtime_queues`` are the
lanes inside it — waiting, priority, VIP, AI, overflow — each with its own
capacity. Conflating them is what makes "the support queue is full" an
unanswerable statement.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.customer_context import ContactPreference, CustomerTier
from blinkengage.domain.runtime_queues import (
    AiOverflowPolicy,
    OverflowStrategy,
    RuntimeQueueKind,
)
from blinkengage.domain.service_context import ContextBindingReason
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class Service(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One thing a customer can be helped with.

    The *identity*, not the configuration. Everything a conversation reads —
    SLA targets, AI policy, which queue it feeds — lives on the version, so
    that this row can be renamed or archived without reaching backwards into
    conversations already running.
    """

    __tablename__ = "services"
    __table_args__ = (
        Index(
            "uq_services_company_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_services_company_active", "company_id", "is_active"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: A stable machine-readable handle. Separate from ``name`` because an
    #: external system selecting a service by name breaks the first time
    #: somebody fixes a typo in it.
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), default=None)

    #: Which version new conversations bind to. Deliberately a pointer rather
    #: than a flag on the version: "the current one" is a single fact, and
    #: two rows both claiming to be current is a state no query can resolve.
    #:
    #: ``use_alter=True`` because this closes a cycle — a service points at
    #: its current version and every version points back at its service.
    #: Without it SQLAlchemy cannot order ``create_all``/``drop_all`` and
    #: warns on every test that builds a schema, which is noise loud enough
    #: to bury a real warning. The migration already adds this constraint as
    #: a separate step for the same reason.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey(
            "service_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_services_current_version",
        ),
        default=None,
    )

    #: An inactive service takes no new conversations. Distinct from
    #: soft-deletion, which also hides it from the directory: a seasonal
    #: service is switched off and on, not deleted and recreated.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: Where the resolution pipeline offers it to a customer, when the
    #: CUSTOMER_SELECTION stage is in use. Lower sorts first.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ServiceVersion(UUIDPrimaryKeyMixin, Base):
    """One frozen configuration of a service.

    **Append-only**, enforced by a trigger on PostgreSQL. A conversation binds
    to a version and reads it for its whole life; an administrator halving a
    response target at noon must not rewrite the deadline of every
    conversation opened that morning.

    No ``TimestampMixin`` and no ``SoftDeleteMixin``, for the same reasons as
    ``routing_decisions``: ``updated_at`` on a row that cannot be updated is
    noise, and a delete flag on an append-only table hides what the trigger
    exists to protect.
    """

    __tablename__ = "service_versions"
    __table_args__ = (
        # Version numbers are per service and gapless from 1. The constraint
        # is what makes two concurrent edits produce an error rather than two
        # rows both calling themselves version 4.
        UniqueConstraint("service_id", "version", name="uq_service_versions_service_version"),
        Index("ix_service_versions_service", "service_id", "version"),
    )

    service_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Carried **by value**, not read through ``service_id`` at display time.
    #: A conversation must still be able to say what it is running in after
    #: the service is renamed or archived.
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Queue binding ------------------------------------------------
    #: SET NULL rather than CASCADE: deleting a queue must not delete the
    #: history of every service that once fed it. A version whose queue is
    #: gone is a service that can no longer route, which the Policy Engine
    #: reports as ``NO_QUEUE_CONFIGURED`` rather than crashing on a null.
    logical_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="SET NULL"), default=None
    )
    logical_queue_name: Mapped[str | None] = mapped_column(String(255), default=None)
    overflow_strategy: Mapped[OverflowStrategy] = mapped_column(
        Enum(OverflowStrategy, native_enum=False, length=30),
        nullable=False,
        default=OverflowStrategy.WAIT,
    )
    ai_overflow_policy: Mapped[AiOverflowPolicy] = mapped_column(
        Enum(AiOverflowPolicy, native_enum=False, length=30),
        nullable=False,
        default=AiOverflowPolicy.NEVER,
    )

    # --- The four SLA clocks ------------------------------------------
    #
    # Four independent nullable columns, not one policy id. ``None`` means
    # "not measured" and is different from ``0``, which means "already
    # breached the moment it starts" — folding them together would invent a
    # deadline nobody set. A sales service with a hard first-response target
    # and no resolution target is a real configuration.
    sla_queue_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    sla_first_response_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    sla_next_response_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    sla_resolution_minutes: Mapped[int | None] = mapped_column(Integer, default=None)

    # --- AI policy ----------------------------------------------------
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Seconds AI waits before answering, so a human has a chance to get
    #: there first. An AI that always replies instantly removes that chance.
    ai_pickup_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    ai_resume_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    #: Stored as text, read back as ``Decimal``. A threshold compared against
    #: a model's confidence must not have two numbers differing in the last
    #: binary place straddle it — see ``domain/service_context.py``.
    ai_confidence_threshold: Mapped[str] = mapped_column(String(16), nullable=False, default="0.75")

    #: Namespaced settings for modules that did not exist when this version
    #: was written. Read through ``ServiceContext.setting()``, which answers
    #: with the caller's default rather than raising — the seam that lets a
    #: conversation bound to an old version keep running.
    extras: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    #: SET NULL: an administrator who has left must not take the history of
    #: what they configured with them.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Why this version exists, in an operator's words. Shown beside the
    #: version in the console, so "why did the SLA change in March?" has an
    #: answer that is not archaeology.
    change_note: Mapped[str | None] = mapped_column(String(500), default=None)


class CustomerContextVersion(UUIDPrimaryKeyMixin, Base):
    """One frozen set of a customer's routing-relevant attributes.

    **Append-only**, like ``service_versions``, and minted from a
    *fingerprint* rather than on every edit.

    A service changes when an administrator edits it: rarely, deliberately. A
    customer record changes constantly — a CRM sync writes a field back, an
    agent corrects a phone number. Minting a version on every change would
    produce one per conversation, a chain nobody can read, and effectively no
    versioning at all. So a row is written only when the fingerprint of the
    routing-relevant attributes actually moves: renaming a customer does not
    fork their history, promoting them to VIP does.
    """

    __tablename__ = "customer_context_versions"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "version", name="uq_customer_context_versions_customer_version"
        ),
        # The lookup on every conversation start: "does this customer's
        # current profile already have a version?" Fingerprint first because
        # it is the selective half.
        Index("ix_customer_context_versions_fingerprint", "customer_id", "fingerprint"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    #: SHA-256 hex of the routing-relevant attributes, canonically ordered.
    #: Not Python's ``hash()``, which is salted per process and would fork
    #: every customer's history on restart.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    #: By value, so a conversation can name the customer it is with even
    #: after the customer record is renamed or erased.
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    tier: Mapped[CustomerTier] = mapped_column(
        Enum(CustomerTier, native_enum=False, length=20),
        nullable=False,
        default=CustomerTier.STANDARD,
    )
    #: Separate from ``tier`` on purpose: a company can mark somebody VIP for
    #: one campaign without moving their commercial tier.
    is_vip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    language: Mapped[str | None] = mapped_column(String(16), default=None)
    timezone: Mapped[str | None] = mapped_column(String(64), default=None)
    country_code: Mapped[str | None] = mapped_column(String(2), default=None)

    #: Commercial position, carried as values. The billing domain owns these
    #: objects; live references here would be a second place billing
    #: configuration could be read from. No FK for the same reason.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    contract_name: Mapped[str | None] = mapped_column(String(255), default=None)
    pricing_profile_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    segment: Mapped[str | None] = mapped_column(String(120), default=None)

    contact_preference: Mapped[ContactPreference] = mapped_column(
        Enum(ContactPreference, native_enum=False, length=30),
        nullable=False,
        default=ContactPreference.ANY,
    )
    #: Advisory, not an instruction: a conversation that waits for one
    #: specific person is a conversation nobody answers.
    preferred_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    extras: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )


class RuntimeQueue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One lane inside a logical queue.

    The distinction the queue architecture rests on. ``queues`` is what an
    administrator names, assigns agents to and reports on; a *runtime queue*
    is a lane within it with its own capacity — waiting, priority, VIP, the
    lane AI works, and the lane conversations overflow into.

    Without the split, "the support queue is full" cannot be answered:
    full for whom, and does a VIP arriving now wait behind sixty other
    people? With it, each lane has its own depth and its own answer.
    """

    __tablename__ = "runtime_queues"
    __table_args__ = (
        # One lane of each kind per logical queue. Two "priority" lanes in
        # one queue is a configuration with no meaning: a conversation
        # entering priority would have no defined destination.
        UniqueConstraint("logical_queue_id", "kind", name="uq_runtime_queues_queue_kind"),
        Index("ix_runtime_queues_company", "company_id", "is_active"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    logical_queue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[RuntimeQueueKind] = mapped_column(
        Enum(RuntimeQueueKind, native_enum=False, length=30), nullable=False
    )

    #: How many conversations may wait here. **Zero means unlimited**, not
    #: "closed" — a lane that refused everything would drop conversations,
    #: and the guarantee this whole design makes is that a full lane never
    #: refuses one. See ``domain/runtime_queues.py``.
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Where conversations go when this lane is full. Self-referencing and
    #: nullable: a lane with no overflow target and an overflow strategy
    #: records ``OVERFLOW_LANE_MISSING`` rather than silently behaving as if
    #: it were configured to wait.
    overflow_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("runtime_queues.id", ondelete="SET NULL"), default=None
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ConversationContextBinding(UUIDPrimaryKeyMixin, Base):
    """Which contexts a conversation is running inside, and why.

    **Append-only.** A rebinding is a new row, not an edit — "this
    conversation was moved to another service on the 3rd, by Sara, because
    the customer had reached the wrong team" is exactly the question this
    table exists to answer, and an UPDATE would erase it.

    The conversation's *current* binding is the newest row for it. That is
    one index away and always correct, whereas a mutable column on
    ``conversations`` plus a history table is two writes that can disagree.
    """

    __tablename__ = "conversation_context_bindings"
    __table_args__ = (
        Index(
            "ix_conversation_context_bindings_current",
            "conversation_id",
            "bound_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    #: RESTRICT, deliberately, and the only RESTRICT here. Deleting a service
    #: version that a conversation is bound to would leave that conversation
    #: unable to say what rules it ran under — the one thing the whole
    #: versioning design exists to guarantee. Versions are append-only
    #: anyway, so this only ever fires against a manual DELETE.
    service_version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("service_versions.id", ondelete="RESTRICT"), nullable=False
    )
    #: Nullable: a first message on anonymous web chat, or an unrecognised
    #: number, is a normal case and not an error.
    customer_context_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customer_context_versions.id", ondelete="RESTRICT"), default=None
    )

    reason: Mapped[ContextBindingReason] = mapped_column(
        Enum(ContextBindingReason, native_enum=False, length=40),
        nullable=False,
        default=ContextBindingReason.BOUND_AT_START,
    )
    bound_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    bound_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(String(500), default=None)


__all__ = [
    "ConversationContextBinding",
    "CustomerContextVersion",
    "RuntimeQueue",
    "Service",
    "ServiceVersion",
]
