from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.inbox_views import InboxView
from blinkengage.domain.lifecycle import FINISHED
from blinkengage.domain.operational_state import (
    OperationalState,
    StateFacts,
    operational_state,
)
from blinkengage.domain.ownership import Owner, OwnerKind
from blinkengage.domain.routing_decisions import RoutingDecisionKind
from blinkengage.domain.sla import SEVERITY, SlaHealth
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationPriority,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership
from blinkengage.infrastructure.database.models.routing_decision import (
    RoutingDecisionRecord,
)
from blinkengage.infrastructure.repositories.sla_health_rank import (
    conversation_ranks,
    health_of,
)

#: Read once so the SQL and the domain cannot disagree about which number
#: means which band.
SEVERITY_AT_RISK = SEVERITY[SlaHealth.AT_RISK]
SEVERITY_BREACHED = SEVERITY[SlaHealth.BREACHED]

# ConversationPriority's stored strings ("LOW"/"NORMAL"/"HIGH"/"URGENT"
# — Enum(native_enum=False) stores a StrEnum member's NAME, not its
# lowercase .value; confirmed against conversations.status storing
# "OPEN", not "open") don't sort correctly alphabetically ("HIGH" <
# "LOW" < "NORMAL" < "URGENT") — this CASE expression gives the Inbox's
# default sort a genuine urgency ranking to order by instead.
_PRIORITY_RANK = case(
    {
        ConversationPriority.URGENT.name: 3,
        ConversationPriority.HIGH.name: 2,
        ConversationPriority.NORMAL.name: 1,
        ConversationPriority.LOW.name: 0,
    },
    value=Conversation.priority,
    else_=1,
)


@dataclass(frozen=True, slots=True)
class InboxRow:
    """One conversation as the Inbox needs it, not as it is stored.

    The Inbox is an operations screen: every row has to answer who, how
    healthy, who owns it, what happened and what to do, and none of those are
    columns on ``conversations``. Carrying them here — resolved by the same
    query that found the row — is what stops the browser making a request per
    conversation to fill them in.

    That was not hypothetical. The customer's name, the single most important
    identifier on the screen, was fetched one row at a time: twenty rows meant
    twenty requests, each with its own skeleton, so the name arrived last and
    staggered while the metadata around it was already drawn.
    """

    conversation: Conversation
    sla_health: SlaHealth
    #: ``None`` for a customer row that has been deleted underneath the
    #: conversation. The Inbox shows the id rather than an empty cell, so a
    #: missing name reads as a data problem rather than a rendering one.
    customer_name: str | None
    #: What the conversation is waiting on — the row's most important line.
    #: Described, never prescribed: see ``domain/operational_state.py``.
    state: OperationalState
    #: Who is answerable, from the ownership timeline rather than inferred
    #: from ``assigned_agent_id``. Assignment and ownership are deliberately
    #: separate concepts, and an Inbox that showed one while calling it the
    #: other would undo the distinction M3 exists to make.
    owner: Owner
    #: When responsibility last moved, which is the closest thing the
    #: platform records to "how long has it been like this". ``None`` before
    #: anything has ever owned it.
    owner_since: datetime | None
    #: The last thing the *platform* decided about this conversation, in the
    #: sentence whichever engine decided it already wrote — "AI Autopilot
    #: took the conversation", "Routed to the Support queue", "The first
    #: response target was missed".
    #:
    #: Distinct from the last *message*, which is what the customer said and
    #: sits after this on the row. An agent needs to know what changed since
    #: they last looked before they need to know the wording of it.
    #:
    #: ``None`` for a conversation with no decisions — one that predates the
    #: decision log, or never reached routing.
    last_event: str | None
    last_event_kind: str | None
    last_event_at: datetime | None


#: Every view the workload strip counts. ``MINE`` is included and simply
#: returns zero when nobody is asking as an agent, which is honest — a
#: supervisor genuinely has none assigned to them.
_COUNTED_VIEWS: tuple[InboxView, ...] = tuple(InboxView)


def _start_of_day(moment: datetime) -> datetime:
    """Midnight, in UTC.

    "Resolved today" is a real question with a real edge: an installation
    spanning time zones will disagree about when today started. UTC is the
    same answer for everybody and matches how every other date in this
    platform is stored; per-company business hours would be a better answer
    and a larger change than this milestone should make.
    """
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _ours_to_move() -> Any:
    """SQL for "the business is the one being waited on".

    The same rule ``OURS_TO_MOVE`` states in the domain, expressed once here
    because a view has to be a server-side query. That makes it the second
    expression of one rule, which is the shape that drifts — so
    ``test_inbox_views.py`` checks that every conversation a view returns is
    really in a state the view claims, rather than trusting these to agree.
    """
    return and_(
        Conversation.status.not_in(FINISHED),
        Conversation.status != ConversationStatus.WAITING_CUSTOMER,
        Conversation.autopilot_active.is_(False),
        Conversation.ai_pickup_eligible_at.is_(None),
    )


def _view_condition(view: InboxView, *, agent_id: UUID | None, rank: Any, today: datetime) -> Any:
    """What each work queue means, in SQL.

    Written to mirror ``operational_state``'s branches exactly — the
    conditions below are the same ones that derivation reads, in the same
    order of precedence.
    """
    unfinished = Conversation.status.not_in(FINISHED)

    if view is InboxView.ACTIVE:
        return unfinished
    if view is InboxView.WAITING_PICKUP:
        return and_(_ours_to_move(), Conversation.assigned_agent_id.is_(None))
    if view is InboxView.MINE:
        if agent_id is None:
            # Not "everything unassigned". ``column == None`` compiles to
            # ``IS NULL``, so asking for "mine" without an agent identity
            # returned every conversation nobody had taken — a supervisor
            # opening the Inbox would have been told the whole backlog was
            # theirs. Nobody's list is empty.
            return false()
        return and_(unfinished, Conversation.assigned_agent_id == agent_id)
    if view is InboxView.AI_WORKING:
        return and_(
            unfinished,
            or_(
                Conversation.autopilot_active.is_(True),
                Conversation.ai_pickup_eligible_at.is_not(None),
            ),
        )
    if view is InboxView.WAITING_CUSTOMER:
        return and_(
            unfinished,
            Conversation.autopilot_active.is_(False),
            Conversation.ai_pickup_eligible_at.is_(None),
            Conversation.status == ConversationStatus.WAITING_CUSTOMER,
        )
    if view is InboxView.AT_RISK:
        return and_(unfinished, rank == SEVERITY_AT_RISK)
    if view is InboxView.BREACHED:
        return and_(unfinished, rank == SEVERITY_BREACHED)
    if view is InboxView.RESOLVED_TODAY:
        return and_(Conversation.status.in_(FINISHED), Conversation.updated_at >= today)
    # NEEDS_ATTENTION: ours to move, and either out of time or unattended.
    # A conversation waiting on a customer is not neglected, and one AI is
    # answering does not need an agent — both are excluded by _ours_to_move.
    return and_(
        _ours_to_move(),
        or_(rank >= SEVERITY_AT_RISK, Conversation.assigned_agent_id.is_(None)),
    )


def _to_inbox_row(row: Any) -> InboxRow:
    """One database row as the Inbox needs it.

    The operational state is derived here, from facts the same query already
    fetched — never stored, so it cannot drift out of step with the
    conversation it describes, and never computed in a browser, so every
    client describes the same conversation the same way.
    """
    # Unpacked by name, not by index. The query grew from two columns to
    # nine while this was being written, and every index shifted with it —
    # positional access here was wrong within one edit of being right.
    (
        conversation,
        rank,
        customer_name,
        owner_kind,
        owner_id,
        owner_name,
        owner_reason,
        owned_from,
        event_sentence,
        event_kind,
        event_at,
    ) = row
    return InboxRow(
        conversation=conversation,
        sla_health=health_of(rank),
        customer_name=customer_name,
        state=operational_state(
            StateFacts(
                status=conversation.status,
                assigned_agent_id=conversation.assigned_agent_id,
                queue_id=conversation.queue_id,
                autopilot_active=bool(conversation.autopilot_active),
                ai_pickup_eligible_at=conversation.ai_pickup_eligible_at,
                owner_kind=owner_kind,
                owner_reason=owner_reason,
            )
        ),
        owner=Owner(kind=owner_kind or OwnerKind.NOBODY, id=owner_id, name=owner_name),
        owner_since=owned_from,
        last_event=event_sentence,
        last_event_kind=event_kind.value if event_kind is not None else None,
        last_event_at=event_at,
    )


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, conversation_id: UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_any_company(self, conversation_id: UUID) -> Conversation | None:
        """Unscoped by ``company_id`` — the public CSAT survey-response
        endpoint (see ``docs/architecture/reports-analytics.md``) carries
        no JWT/tenant context, only a signed CSAT token whose ``sub``
        claim already pins it to this exact conversation id. Security
        here is the token's signature, not tenant isolation."""
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_thread(
        self, *, channel_config_id: UUID, external_thread_id: str
    ) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.channel_config_id == channel_config_id,
                Conversation.external_thread_id == external_thread_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        status: ConversationStatus | None = None,
        customer_id: UUID | None = None,
        assigned_agent_id: UUID | None = None,
        queue_id: UUID | None = None,
        priority: ConversationPriority | None = None,
        unassigned_only: bool = False,
        view: InboxView | None = None,
        viewer_agent_id: UUID | None = None,
        now: datetime | None = None,
    ) -> tuple[list[InboxRow], int]:
        """A page of the Inbox, worst SLA health first.

        Returns each row already carrying what the screen needs — see
        ``InboxRow``. The health has been computed anyway, to sort by; the
        customer's name costs one join here and one request per row anywhere
        else.
        """
        moment = now or datetime.now(UTC)
        base = select(Conversation).where(
            Conversation.company_id == company_id, Conversation.deleted_at.is_(None)
        )
        if status is not None:
            base = base.where(Conversation.status == status)
        if customer_id is not None:
            base = base.where(Conversation.customer_id == customer_id)
        if assigned_agent_id is not None:
            base = base.where(Conversation.assigned_agent_id == assigned_agent_id)
        if queue_id is not None:
            base = base.where(Conversation.queue_id == queue_id)
        if priority is not None:
            base = base.where(Conversation.priority == priority)
        if unassigned_only:
            base = base.where(Conversation.assigned_agent_id.is_(None))
        ranks_for_filter = conversation_ranks(self._session, now=moment, company_id=company_id)
        if view is not None:
            # Joined before counting, so the total matches the page. A count
            # that ignored the view would put "1 of 40" under four rows.
            base = base.outerjoin(
                ranks_for_filter, ranks_for_filter.c.conversation_id == Conversation.id
            ).where(
                _view_condition(
                    view,
                    agent_id=viewer_agent_id,
                    rank=func.coalesce(ranks_for_filter.c.rank, SEVERITY[SlaHealth.HEALTHY]),
                    today=_start_of_day(moment),
                )
            )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Conversation.id).subquery())
            )
        ).scalar_one()
        # SLA health leads the ordering, ahead of priority. The two answer
        # different questions and both belong: health is "is this one running
        # out of time", priority is "does this one matter more". A breached
        # NORMAL conversation outranks a healthy URGENT one, because the
        # urgent one still has time to be handled and the other does not.
        # The newest ownership row per conversation. A window function
        # rather than DISTINCT ON, which PostgreSQL has and SQLite does not —
        # the tests run on one and production on the other, and a query that
        # only works on one of them is a query that fails where it matters.
        ranked_ownership = (
            select(
                ConversationOwnership.conversation_id.label("conversation_id"),
                ConversationOwnership.owner_kind.label("owner_kind"),
                ConversationOwnership.owner_id.label("owner_id"),
                ConversationOwnership.owner_name.label("owner_name"),
                ConversationOwnership.reason.label("reason"),
                ConversationOwnership.owned_from.label("owned_from"),
                func.row_number()
                .over(
                    partition_by=ConversationOwnership.conversation_id,
                    order_by=ConversationOwnership.owned_from.desc(),
                )
                .label("recency"),
            )
            .where(ConversationOwnership.company_id == company_id)
            .subquery()
        )
        current_owner = select(ranked_ownership).where(ranked_ownership.c.recency == 1).subquery()

        # The last meaningful decision per conversation. Policy evaluations
        # are excluded: they are *gates*, recorded just before the act they
        # authorise, so the newest one is almost always "a rule was checked"
        # rather than the thing that actually happened.
        ranked_events = (
            select(
                RoutingDecisionRecord.conversation_id.label("conversation_id"),
                RoutingDecisionRecord.sentence.label("sentence"),
                RoutingDecisionRecord.kind.label("kind"),
                RoutingDecisionRecord.decided_at.label("decided_at"),
                func.row_number()
                .over(
                    partition_by=RoutingDecisionRecord.conversation_id,
                    order_by=RoutingDecisionRecord.decided_at.desc(),
                )
                .label("recency"),
            )
            .where(
                RoutingDecisionRecord.company_id == company_id,
                RoutingDecisionRecord.kind != RoutingDecisionKind.POLICY_EVALUATED,
            )
            .subquery()
        )
        last_event = select(ranked_events).where(ranked_events.c.recency == 1).subquery()

        ranks = conversation_ranks(self._session, now=moment, company_id=company_id)
        health_rank = func.coalesce(ranks.c.rank, SEVERITY[SlaHealth.HEALTHY])
        result = await self._session.execute(
            base.add_columns(
                ranks.c.rank,
                Customer.full_name,
                current_owner.c.owner_kind,
                current_owner.c.owner_id,
                current_owner.c.owner_name,
                current_owner.c.reason,
                current_owner.c.owned_from,
                last_event.c.sentence,
                last_event.c.kind,
                last_event.c.decided_at,
            )
            .outerjoin(ranks, ranks.c.conversation_id == Conversation.id)
            # Outer: a conversation that predates the ownership model has no
            # row, and must still appear.
            .outerjoin(current_owner, current_owner.c.conversation_id == Conversation.id)
            # Outer again: a conversation with nothing recorded still belongs
            # in the Inbox, and is exactly the one somebody should look at.
            .outerjoin(last_event, last_event.c.conversation_id == Conversation.id)
            # Outer, not inner: a conversation whose customer row was deleted
            # must still appear. It is exactly the row somebody needs to see.
            .outerjoin(Customer, Customer.id == Conversation.customer_id)
            .order_by(
                health_rank.desc(),
                # Then urgent-first, then most-recently-active within a
                # priority tier — every conversation defaults to NORMAL,
                # so this is a strict no-op change in ordering until
                # priorities actually diverge.
                _PRIORITY_RANK.desc(),
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return ([_to_inbox_row(row) for row in result.all()], total)

    async def workload(
        self,
        *,
        company_id: UUID,
        viewer_agent_id: UUID | None = None,
        now: datetime | None = None,
    ) -> dict[InboxView, int]:
        """How many conversations are in each work queue, company-wide.

        One query, not nine: every count is a conditional aggregate over the
        same scan, so the strip costs what a single list costs.

        Counted across the company rather than over the loaded page — a count
        derived from fifty rows would be wrong in exactly the situation it
        matters, which is a busy queue. That is the same reason the SLA
        ordering ranks in SQL.
        """
        moment = now or datetime.now(UTC)
        ranks = conversation_ranks(self._session, now=moment, company_id=company_id)
        rank = func.coalesce(ranks.c.rank, SEVERITY[SlaHealth.HEALTHY])
        today = _start_of_day(moment)

        columns = [
            func.count().filter(
                _view_condition(view, agent_id=viewer_agent_id, rank=rank, today=today)
            )
            for view in _COUNTED_VIEWS
        ]
        result = await self._session.execute(
            select(*columns)
            .select_from(Conversation)
            .outerjoin(ranks, ranks.c.conversation_id == Conversation.id)
            .where(Conversation.company_id == company_id, Conversation.deleted_at.is_(None))
        )
        return dict(zip(_COUNTED_VIEWS, (value or 0 for value in result.one()), strict=True))

    async def health_for(
        self, *, company_id: UUID, conversation_ids: list[UUID], now: datetime | None = None
    ) -> dict[UUID, SlaHealth]:
        """SLA health for conversations already in hand, in one query.

        For the endpoints that return a single conversation. ``list_for_company``
        does not use this — it gets health from the query that sorted by it,
        rather than asking twice.

        A conversation absent from the result has no clocks, and the caller's
        ``.get(id, HEALTHY)`` is the right answer for it.
        """
        if not conversation_ids:
            return {}
        ranks = conversation_ranks(
            self._session,
            now=now or datetime.now(UTC),
            company_id=company_id,
            conversation_ids=conversation_ids,
        )
        result = await self._session.execute(select(ranks.c.conversation_id, ranks.c.rank))
        return {row[0]: health_of(row[1]) for row in result.all()}

    async def claim(self, *, conversation_id: UUID, agent_id: UUID, now: datetime) -> bool:
        """Atomically assigns an unassigned conversation to ``agent_id``
        via a single conditional ``UPDATE`` — not a read-then-write —
        so two agents racing to pick the same conversation can't both
        succeed. Returns ``True`` iff this call actually claimed it
        (exactly one row matched); ``False`` means someone else (or a
        soft-delete) got there first, and the caller (``ConversationService
        .pick()``) turns that into ``ConversationAlreadyClaimedError``.

        ``first_picked_up_at`` is only ever written once — ``COALESCE``
        keeps whatever value it already holds from an earlier claim, so a
        conversation that's been picked, released, and picked again still
        reports the time of its *first* claim ever (see the column's own
        docstring on ``Conversation`` and ``ReportingRepository
        .queue_metrics()``'s ``abandoned_count_24h``)."""
        result = await self._session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.assigned_agent_id.is_(None),
                Conversation.deleted_at.is_(None),
            )
            .values(
                assigned_agent_id=agent_id,
                picked_up_at=now,
                first_picked_up_at=func.coalesce(Conversation.first_picked_up_at, now),
                # A human claiming this conversation always takes it back
                # from AI Autopilot, whether or not it was ever active —
                # see Conversation.autopilot_active's docstring.
                autopilot_active=False,
            )
        )
        return result.rowcount == 1

    async def add(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = datetime.now(UTC)
        await self._session.flush()

    # A generous but still finite cap, same reasoning as reports/audit-log
    # export's own row limits — a cheap safety net against a pathological
    # case, not real pagination (see list_all_for_agent's docstring).
    _MAX_AGENT_REMOVAL_CONVERSATIONS = 10_000

    async def list_all_for_agent(self, *, company_id: UUID, agent_id: UUID) -> list[Conversation]:
        """Every conversation currently assigned to ``agent_id``, whatever
        its status — unpaginated, unlike ``list_for_company``. Used only
        by the agent-removal flow (transfer-all/delete-all-then-remove,
        see ``api.v1.endpoints.agents``'s ``remove_agent``), never a
        user-facing list."""
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.company_id == company_id,
                Conversation.assigned_agent_id == agent_id,
                Conversation.deleted_at.is_(None),
            )
            .limit(self._MAX_AGENT_REMOVAL_CONVERSATIONS)
        )
        return list(result.scalars().all())
