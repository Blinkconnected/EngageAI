"""The routing decision record. See ``docs/architecture/queues-routing.md``.

One table, append-only, and deliberately **denormalized** — the same shape
and for the same reason as ``ledger_entries`` and
``financial_audit_events``. A decision carries the queue's name, the
agent's name, and the routing rule that matched (its id, its rendered
name, its conditions) as *values*, and points at none of them by foreign
key. Routing rules are edited and deleted through an admin screen every
week; queues are renamed and soft-deleted; agents leave. A decision that
needed those rows to still hold their original values would not be an
explanation, it would be a query that happens to work today.

**Append-only.** A decision is a historical fact: correcting one means
recording another, never amending it. There is no update and no delete on
``RoutingDecisionRepository``, and on PostgreSQL a trigger refuses both
outright, so immutability survives a ``psql`` session and not merely
repository discipline. The trigger is guarded in the migration so the
SQLite test backend, which cannot run plpgsql, still builds the schema.

**Growth rate: one to two rows per *conversation*, never per message.**
A new conversation writes the queue decision (chosen, or explicitly left
unrouted) and then at most one of: the agent decision, the "AI took it"
decision, or the "the queue could not take it" decision. Routing runs
only on a conversation's *first* message (queues-routing.md decision #1),
so a 200-message thread still produces exactly the same two rows as a
one-message thread. At the 5M-conversation scale the SLA sweep is
designed against, that is ~10M rows — comparable to ``conversations``
itself and an order of magnitude below ``messages``.

**Retention keys on ``decided_at``.** Rows are never updated, are written
in ``decided_at`` order, and are read either by ``conversation_id`` (a
live conversation, always recent) or by ``company_id`` within a recent
window — so pruning or range-partitioning by month detaches cold rows
without touching anything a console reads. A retention policy should
delete by ``decided_at < cutoff``; it must **not** key on conversation
status, because the conversations somebody asks about years later
("why was this never answered?") are exactly the closed ones.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.routing_decisions import (
    MAX_RULE_NAME,
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
)
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class RoutingDecisionRecord(UUIDPrimaryKeyMixin, Base):
    """One recorded routing/assignment decision about one conversation.

    Named ``…Record`` rather than ``RoutingDecision`` because
    ``domain.routing_decisions.RoutingDecision`` already holds that name
    for the decision *itself* — the framework-free shape the engines
    return and the tests reason about. This class is the row that shape
    is written to, and keeping the two names distinct means no module
    that touches both has to alias one of them.

    No ``TimestampMixin`` and no ``SoftDeleteMixin``: ``updated_at`` on a
    row that can never be updated is noise, and a soft-delete flag on an
    append-only table is a way to hide evidence that the trigger this
    table's migration installs exists to prevent.
    """

    __tablename__ = "routing_decisions"
    __table_args__ = (
        # The two queries that matter, and the only two.
        #
        # "Everything that happened to this conversation, in order" — the
        # conversation-detail explanation panel, and the query a support
        # engineer runs with a ticket number in hand.
        Index("ix_routing_decisions_conversation", "conversation_id", "decided_at"),
        # "Recent decisions for this company" — the operations console's
        # firehose, always read newest-first with a LIMIT. Plain ascending
        # order: a btree scans backwards just as cheaply, and ``decided_at``
        # is NOT NULL so there is no NULLS-ordering nuance to encode
        # (which is what would have forced a per-dialect ``text()`` index
        # here, the way ``ix_conversations_company_last_message`` needed).
        Index("ix_routing_decisions_company_recent", "company_id", "decided_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: CASCADE, unlike ``ledger_entries.company_id``'s SET NULL: a decision
    #: is only meaningful *about* a conversation, so a decision that
    #: outlived its conversation would be an orphan nobody could read, not
    #: evidence worth keeping. Nothing in this codebase hard-deletes a
    #: conversation (they soft-delete), so the DELETE half of the
    #: append-only trigger is never reached through this cascade in
    #: practice — the same combination ``usage_records`` already runs.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    #: Assigned by the repository from the application clock, **not** left
    #: to the server default. PostgreSQL's ``now()`` is transaction-start
    #: time, so every decision written about one conversation — which all
    #: happen inside a single ingest transaction — would carry an
    #: identical timestamp and "in order" would be a lie; SQLite's
    #: ``CURRENT_TIMESTAMP`` is worse still at one-second resolution. The
    #: server default is kept as a floor for anything inserted outside the
    #: repository, never as the normal path. See
    #: ``RoutingDecisionRepository.for_conversation`` for the ordering
    #: this makes honest, and ``LedgerEntry.entry_number`` for the same
    #: problem solved with a gapless counter where gaplessness itself was
    #: the requirement.
    decided_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )

    kind: Mapped[RoutingDecisionKind] = mapped_column(
        Enum(RoutingDecisionKind, native_enum=False, length=30), nullable=False
    )
    outcome: Mapped[RoutingDecisionOutcome] = mapped_column(
        Enum(RoutingDecisionOutcome, native_enum=False, length=20), nullable=False
    )
    reason: Mapped[RoutingDecisionReason] = mapped_column(
        Enum(RoutingDecisionReason, native_enum=False, length=40), nullable=False
    )

    #: Plain columns, **no foreign key**, on purpose. A ``SET NULL`` on a
    #: deleted queue would erase which queue was chosen — precisely the
    #: fact the row exists to hold — and a ``RESTRICT`` would make an
    #: audit table block ordinary administration.
    selected_queue_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    selected_queue_name: Mapped[str | None] = mapped_column(String(255), default=None)
    selected_agent_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    #: The agent's own name, denormalized like
    #: ``FinancialAuditEvent.actor_name`` — an id alone turns every
    #: decision about somebody who has since left into an anonymous one.
    selected_agent_name: Mapped[str | None] = mapped_column(String(255), default=None)

    #: The service the conversation was bound to, and which version of it.
    #: No foreign key, for the same reason as the queue above: a decision
    #: must survive the service being archived, and this row is evidence
    #: rather than a live reference.
    selected_service_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    selected_service_name: Mapped[str | None] = mapped_column(String(255), default=None)
    service_version: Mapped[int | None] = mapped_column(Integer, default=None)
    #: Every stage the resolution pipeline ran, in order, whether or not it
    #: decided. JSON rather than a child table for the same reason as
    #: ``rejected_candidates``: written once with its parent, read whole,
    #: never queried across rows.
    resolution_stages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )

    #: The routing rule that matched, copied. ``matched_rule_name`` is
    #: rendered from the rule's conditions (``RoutingRule`` has no name
    #: column) and frozen here, so editing a rule never rewrites the
    #: history of what it once matched.
    matched_rule_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    #: Width matches ``domain.routing_decisions.MAX_RULE_NAME``, which is
    #: where the clip is applied — nothing caps the length of a rule's
    #: ``body_contains`` value, and an over-long name would cost the
    #: decision its row rather than merely its tail.
    matched_rule_name: Mapped[str | None] = mapped_column(String(MAX_RULE_NAME), default=None)
    matched_rule_priority: Mapped[int | None] = mapped_column(Integer, default=None)
    #: How many active rules were evaluated before this conclusion — the
    #: difference between "your one rule missed" and "all forty missed".
    rules_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Which assignment strategy ran, as a value. A queue's strategy is
    #: reconfigured freely; the decision must keep saying which one
    #: actually decided it.
    strategy: Mapped[str | None] = mapped_column(String(30), default=None)
    #: Every agent the engine looked at, including ones truncated out of
    #: ``rejected_candidates`` — so a list view can show the size of the
    #: field without parsing JSON.
    candidates_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: ``[{"agent_id", "agent_name", "reason"}]`` — who was passed over and
    #: why. JSON rather than a child table: it is written once with its
    #: parent, read only with its parent, and never queried relationally,
    #: so a second table would buy a join and nothing else. Capped at
    #: ``MAX_RECORDED_REJECTIONS`` entries by the domain layer, with the
    #: overflow counted in ``rejections_omitted`` so a truncated list never
    #: reads as a complete one.
    rejected_candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    rejections_omitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: The decision rendered as a sentence, frozen at write time — for
    #: logs, exports and a support engineer with a customer on the phone.
    #: Stored *alongside* the structured fields, never instead of them:
    #: the codes above are what a console filters and localises on. Frozen
    #: rather than re-rendered on read for the same reason
    #: ``LedgerEntry.description`` is: an export produced in 2027 must read
    #: the way it read the day it was decided, even if the wording here
    #: has since been improved.
    sentence: Mapped[str] = mapped_column(Text, nullable=False)

    #: Decision-specific extras that differ per kind and are never queried
    #: relationally — the matched rule's raw conditions today. A JSON blob
    #: rather than a column per variant, matching
    #: ``FinancialAuditEvent.details``.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["RoutingDecisionRecord"]
