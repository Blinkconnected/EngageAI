"""Persistence for the Service Directory.

See ``docs/architecture/execution-context.md``.

Three of these tables are append-only, so the repositories expose **no method
that changes a row** — the same discipline as ``UsagePeriodLineRepository``.
Editing a service means minting a version; rebinding a conversation means
writing a binding. On PostgreSQL a trigger backs that up, so the guarantee
also survives a ``psql`` session.

The reads here all hydrate the **domain** contexts rather than returning ORM
rows, because the whole point of the context architecture is that a module is
handed resolved values and never an id it could look something up with.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.customer_context import (
    ContactPreference,
    CustomerContext,
    CustomerTier,
)
from blinkengage.domain.customer_context import fingerprint as customer_fingerprint
from blinkengage.domain.service_context import (
    AiPolicy,
    QueueBinding,
    ServiceContext,
    SlaTargets,
)
from blinkengage.infrastructure.database.models.service_directory import (
    ConversationContextBinding,
    CustomerContextVersion,
    RuntimeQueue,
    Service,
    ServiceVersion,
)


def to_service_context(row: ServiceVersion) -> ServiceContext:
    """One stored version, as the frozen thing a conversation runs inside.

    Built here rather than in the domain because the domain is
    framework-free and must not know what an ORM row is. This function is
    the only place the two vocabularies meet.
    """
    queue = None
    if row.logical_queue_id is not None:
        queue = QueueBinding(
            logical_queue_id=row.logical_queue_id,
            logical_queue_name=row.logical_queue_name or "",
            overflow_strategy=row.overflow_strategy,
            ai_overflow_policy=row.ai_overflow_policy,
        )
    return ServiceContext(
        service_id=row.service_id,
        version=row.version,
        service_version_id=row.id,
        company_id=row.company_id,
        name=row.name,
        queue=queue,
        sla=SlaTargets(
            queue_minutes=row.sla_queue_minutes,
            first_response_minutes=row.sla_first_response_minutes,
            next_response_minutes=row.sla_next_response_minutes,
            resolution_minutes=row.sla_resolution_minutes,
        ),
        ai=AiPolicy(
            enabled=row.ai_enabled,
            pickup_delay_seconds=row.ai_pickup_delay_seconds,
            resume_delay_seconds=row.ai_resume_delay_seconds,
            # Decimal, from the stored text. Never float: this is compared
            # against a configured threshold, and two numbers differing in
            # the last binary place must not straddle it.
            confidence_threshold=Decimal(row.ai_confidence_threshold),
        ),
        extras=dict(row.extras or {}),
    )


def to_customer_context(row: CustomerContextVersion) -> CustomerContext:
    """One stored customer version, as the frozen context.

    The fingerprint is carried in ``extras['_meta']`` so
    ``customer_context.matches()`` can answer "is this conversation running
    on a stale view of the customer?" without a second query.
    """
    extras = dict(row.extras or {})
    extras.setdefault("_meta", {})
    if isinstance(extras["_meta"], dict):
        extras["_meta"] = {**extras["_meta"], "fingerprint": row.fingerprint}

    return CustomerContext(
        customer_id=row.customer_id,
        version=row.version,
        customer_version_id=row.id,
        company_id=row.company_id,
        display_name=row.display_name,
        tier=row.tier,
        is_vip=row.is_vip,
        language=row.language,
        timezone=row.timezone,
        country_code=row.country_code,
        contract_id=row.contract_id,
        contract_name=row.contract_name,
        pricing_profile_id=row.pricing_profile_id,
        segment=row.segment,
        contact_preference=row.contact_preference,
        preferred_agent_id=row.preferred_agent_id,
        extras=extras,
    )


class ServiceRepository:
    """Services and their versions.

    ``add_version`` is the only way a configuration changes. There is no
    ``update_version`` and there will not be one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, service_id: uuid.UUID) -> Service | None:
        return await self._session.get(Service, service_id)

    async def by_code(self, *, company_id: uuid.UUID, code: str) -> Service | None:
        result = await self._session.execute(
            select(Service).where(
                Service.company_id == company_id,
                Service.code == code,
                Service.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def active_for_company(self, company_id: uuid.UUID) -> list[Service]:
        """What a customer can be offered, in the order an operator chose."""
        result = await self._session.execute(
            select(Service)
            .where(
                Service.company_id == company_id,
                Service.deleted_at.is_(None),
                Service.is_active.is_(True),
            )
            .order_by(Service.display_order, Service.name)
        )
        return list(result.scalars().all())

    async def add(self, service: Service) -> Service:
        self._session.add(service)
        await self._session.flush()
        return service

    async def next_version_number(self, service_id: uuid.UUID) -> int:
        """The next version number for this service.

        Read-then-write, so two concurrent edits can pick the same number —
        which is exactly what ``uq_service_versions_service_version`` is for.
        The loser gets an IntegrityError and retries rather than quietly
        creating a second "version 4". A counter table would serialise every
        edit across the installation to avoid a collision that happens when
        two people edit one service in the same second.
        """
        result = await self._session.execute(
            select(ServiceVersion.version)
            .where(ServiceVersion.service_id == service_id)
            .order_by(ServiceVersion.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return (latest or 0) + 1

    async def add_version(self, version: ServiceVersion) -> ServiceVersion:
        """Writes a new frozen configuration.

        The caller is responsible for pointing ``Service.current_version_id``
        at it — deliberately a separate step, because minting a version and
        making it the one new conversations use are two decisions, and a
        draft that is written but not yet promoted is a thing an operator
        will eventually want.
        """
        self._session.add(version)
        await self._session.flush()
        return version

    async def current_context(self, service_id: uuid.UUID) -> ServiceContext | None:
        """What a conversation starting now would bind to."""
        service = await self.get(service_id)
        if service is None or service.current_version_id is None:
            return None
        row = await self._session.get(ServiceVersion, service.current_version_id)
        return to_service_context(row) if row is not None else None

    async def context_for_version(self, version_id: uuid.UUID) -> ServiceContext | None:
        row = await self._session.get(ServiceVersion, version_id)
        return to_service_context(row) if row is not None else None

    async def versions_for(self, service_id: uuid.UUID, *, limit: int = 50) -> list[ServiceVersion]:
        """Newest first — how a console shows a service's history."""
        result = await self._session.execute(
            select(ServiceVersion)
            .where(ServiceVersion.service_id == service_id)
            .order_by(ServiceVersion.version.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class CustomerContextRepository:
    """Customer versions, minted from a fingerprint.

    ``ensure_version`` is the whole interface that matters: it returns the
    existing version when nothing routing-relevant has moved, and writes a
    new one when something has.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self, customer_id: uuid.UUID) -> CustomerContextVersion | None:
        result = await self._session.execute(
            select(CustomerContextVersion)
            .where(CustomerContextVersion.customer_id == customer_id)
            .order_by(CustomerContextVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def by_fingerprint(
        self, *, customer_id: uuid.UUID, fingerprint: str
    ) -> CustomerContextVersion | None:
        """Any version matching this fingerprint, newest first.

        Matched on the fingerprint rather than only against the newest
        version, so a customer promoted to VIP and then demoted back reuses
        their original version instead of minting a third identical one.
        """
        result = await self._session.execute(
            select(CustomerContextVersion)
            .where(
                CustomerContextVersion.customer_id == customer_id,
                CustomerContextVersion.fingerprint == fingerprint,
            )
            .order_by(CustomerContextVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def ensure_version(
        self,
        *,
        customer_id: uuid.UUID,
        company_id: uuid.UUID,
        display_name: str,
        tier: CustomerTier = CustomerTier.STANDARD,
        is_vip: bool = False,
        language: str | None = None,
        timezone: str | None = None,
        country_code: str | None = None,
        contract_id: uuid.UUID | None = None,
        contract_name: str | None = None,
        pricing_profile_id: uuid.UUID | None = None,
        segment: str | None = None,
        contact_preference: ContactPreference = ContactPreference.ANY,
        preferred_agent_id: uuid.UUID | None = None,
        extras: dict[str, Any] | None = None,
    ) -> CustomerContextVersion:
        """The version matching the customer as they are now, minting one
        only if the routing-relevant attributes have actually moved.

        This is the method that keeps the table readable. Called on every
        conversation start, it writes nothing the overwhelming majority of
        the time — a customer whose name was corrected, or whose
        ``last_seen_at`` was touched, keeps the version they had.
        """
        digest = customer_fingerprint(
            tier=tier,
            is_vip=is_vip,
            language=language,
            timezone=timezone,
            country_code=country_code,
            contract_id=contract_id,
            pricing_profile_id=pricing_profile_id,
            segment=segment,
            contact_preference=contact_preference,
            preferred_agent_id=preferred_agent_id,
            extras=extras,
        )

        existing = await self.by_fingerprint(customer_id=customer_id, fingerprint=digest)
        if existing is not None:
            return existing

        latest = await self.latest(customer_id)
        version = CustomerContextVersion(
            customer_id=customer_id,
            company_id=company_id,
            version=(latest.version if latest else 0) + 1,
            fingerprint=digest,
            # Carried by value and *not* part of the fingerprint: a renamed
            # customer keeps their version, and the new name simply appears
            # on the next version whenever one is minted for another reason.
            display_name=display_name,
            tier=tier,
            is_vip=is_vip,
            language=language,
            timezone=timezone,
            country_code=country_code,
            contract_id=contract_id,
            contract_name=contract_name,
            pricing_profile_id=pricing_profile_id,
            segment=segment,
            contact_preference=contact_preference,
            preferred_agent_id=preferred_agent_id,
            extras=dict(extras or {}),
        )
        self._session.add(version)
        await self._session.flush()
        return version

    async def context_for_version(self, version_id: uuid.UUID) -> CustomerContext | None:
        row = await self._session.get(CustomerContextVersion, version_id)
        return to_customer_context(row) if row is not None else None


class RuntimeQueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lanes_for(self, logical_queue_id: uuid.UUID) -> list[RuntimeQueue]:
        result = await self._session.execute(
            select(RuntimeQueue)
            .where(
                RuntimeQueue.logical_queue_id == logical_queue_id,
                RuntimeQueue.is_active.is_(True),
            )
            .order_by(RuntimeQueue.kind)
        )
        return list(result.scalars().all())

    async def add(self, lane: RuntimeQueue) -> RuntimeQueue:
        self._session.add(lane)
        await self._session.flush()
        return lane


class ContextBindingRepository:
    """Which contexts a conversation runs inside. Append-only.

    No update method: a rebinding is a new row. "Moved to another service on
    the 3rd, by Sara, because the customer reached the wrong team" is the
    question this table answers, and an UPDATE would erase it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current(self, conversation_id: uuid.UUID) -> ConversationContextBinding | None:
        """The newest binding — always the one in force.

        Derived rather than stored as a flag, because a mutable "is_current"
        column plus a history table is two writes that can disagree.
        """
        result = await self._session.execute(
            select(ConversationContextBinding)
            .where(ConversationContextBinding.conversation_id == conversation_id)
            .order_by(ConversationContextBinding.bound_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def history(self, conversation_id: uuid.UUID) -> list[ConversationContextBinding]:
        """Oldest first — the order somebody reads a story in."""
        result = await self._session.execute(
            select(ConversationContextBinding)
            .where(ConversationContextBinding.conversation_id == conversation_id)
            .order_by(ConversationContextBinding.bound_at)
        )
        return list(result.scalars().all())

    async def add(self, binding: ConversationContextBinding) -> ConversationContextBinding:
        self._session.add(binding)
        await self._session.flush()
        return binding


__all__ = [
    "ContextBindingRepository",
    "CustomerContextRepository",
    "RuntimeQueueRepository",
    "ServiceRepository",
    "to_customer_context",
    "to_service_context",
]
