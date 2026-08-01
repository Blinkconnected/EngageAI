"""Creating and editing services.

See ``docs/architecture/execution-context.md``.

One rule shapes this whole module: **a configuration is never edited, only
superseded.** Conversations already running are bound to a version and read it
for their whole life, so an UPDATE would rewrite the rules they ran under —
which is the thing the versioning exists to prevent, and which a PostgreSQL
trigger refuses outright.

So an edit that touches anything a conversation reads mints a new version and
promotes it. An edit that touches only how the service is *administered* —
its code, whether it is switched on, where it sorts — changes the service row
and mints nothing, because none of those change how a bound conversation
behaves.

That distinction is the interesting decision here, and it is drawn field by
field in ``VERSIONED_FIELDS`` rather than left to whoever writes the next
endpoint.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from blinkengage.domain.exceptions import (
    EntityNotFoundError,
    InvalidServiceConfigurationError,
)
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import ServiceContext
from blinkengage.infrastructure.database.models.service_directory import (
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ServiceRepository,
    to_service_context,
)

#: Fields a running conversation reads. Changing any of them mints a version.
#:
#: The name is here, and that is deliberate: a version carries the name by
#: value so a conversation can say what it was running in after the service is
#: archived. If a rename did not mint a version, conversations starting *after*
#: the rename would keep reporting the old name — the snapshot would be
#: protecting history from a change that was supposed to take effect.
VERSIONED_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "logical_queue_id",
        "overflow_strategy",
        "ai_overflow_policy",
        "sla_queue_minutes",
        "sla_first_response_minutes",
        "sla_next_response_minutes",
        "sla_resolution_minutes",
        "ai_enabled",
        "ai_pickup_delay_seconds",
        "ai_resume_delay_seconds",
        "ai_confidence_threshold",
        "extras",
    }
)

#: Fields that describe how the service is administered. A bound conversation
#: does not read any of them, so changing one mints nothing.
IDENTITY_FIELDS: frozenset[str] = frozenset({"code", "description", "is_active", "display_order"})


@dataclass(frozen=True, slots=True)
class ServiceSaved:
    """What an edit actually did.

    ``version_minted`` is returned rather than inferred, so the console can
    say "saved" for a reordering and "version 4 created" for a change to the
    SLA. An administrator who cannot tell the two apart cannot predict which
    of their edits reach conversations already running.
    """

    service: Service
    context: ServiceContext
    version_minted: bool


class ServiceDirectoryService:
    def __init__(self, *, services: ServiceRepository, queues: QueueRepository) -> None:
        self._services = services
        self._queues = queues

    async def list_for_company(self, company_id: uuid.UUID) -> list[Service]:
        return await self._services.active_for_company(company_id)

    async def get(self, *, company_id: uuid.UUID, service_id: uuid.UUID) -> Service:
        service = await self._services.get(service_id)
        # Company checked here rather than in the query, so a service that
        # exists but belongs to somebody else answers the same as one that
        # does not exist — a 404 either way, never a hint that the id is real.
        if service is None or service.company_id != company_id or service.deleted_at is not None:
            raise EntityNotFoundError("Service", service_id)
        return service

    async def context(self, *, company_id: uuid.UUID, service_id: uuid.UUID) -> ServiceContext:
        await self.get(company_id=company_id, service_id=service_id)
        context = await self._services.current_context(service_id)
        if context is None:
            raise EntityNotFoundError("ServiceVersion", service_id)
        return context

    async def versions(
        self, *, company_id: uuid.UUID, service_id: uuid.UUID
    ) -> list[ServiceVersion]:
        await self.get(company_id=company_id, service_id=service_id)
        return await self._services.versions_for(service_id)

    async def create(
        self,
        *,
        company_id: uuid.UUID,
        code: str,
        name: str,
        description: str | None = None,
        display_order: int = 0,
        actor_user_id: uuid.UUID | None = None,
        **configuration: Any,
    ) -> ServiceSaved:
        """Creates a service and its first version.

        A service without a version cannot be resolved into — it has no
        queue, no SLA and no AI policy to read — so the two are created
        together rather than leaving a window in which the directory
        contains something unusable.
        """
        if await self._services.by_code(company_id=company_id, code=code) is not None:
            raise InvalidServiceConfigurationError(
                f"A service with the code '{code}' already exists."
            )

        await self._validate(company_id=company_id, configuration=configuration)

        service = await self._services.add(
            Service(
                company_id=company_id,
                code=code,
                name=name,
                description=description,
                display_order=display_order,
            )
        )
        version = await self._mint(
            service=service,
            company_id=company_id,
            name=name,
            configuration=configuration,
            actor_user_id=actor_user_id,
            change_note="Created",
        )
        return ServiceSaved(
            service=service, context=to_service_context(version), version_minted=True
        )

    async def update(
        self,
        *,
        company_id: uuid.UUID,
        service_id: uuid.UUID,
        changes: dict[str, Any],
        change_note: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ServiceSaved:
        """Applies an edit, minting a version only if one is needed.

        ``changes`` holds only what the caller actually sent — a field left
        out is untouched, not reset. That matters more here than in an
        ordinary PATCH: a missing SLA target read as ``None`` would silently
        stop measuring something, and the version recording it would look
        like a deliberate decision.
        """
        service = await self.get(company_id=company_id, service_id=service_id)
        unknown = set(changes) - VERSIONED_FIELDS - IDENTITY_FIELDS
        if unknown:
            raise InvalidServiceConfigurationError(
                f"Unknown fields: {', '.join(sorted(unknown))}."
            )

        if "code" in changes and changes["code"] != service.code:
            clash = await self._services.by_code(company_id=company_id, code=changes["code"])
            if clash is not None and clash.id != service.id:
                raise InvalidServiceConfigurationError(
                    f"A service with the code '{changes['code']}' already exists."
                )

        current = await self._services.current_context(service_id)
        versioned = {k: v for k, v in changes.items() if k in VERSIONED_FIELDS}
        await self._validate(company_id=company_id, configuration=versioned)

        for field in IDENTITY_FIELDS & set(changes):
            setattr(service, field, changes[field])

        if not versioned or current is None:
            # Nothing a conversation reads has changed. Mutating the service
            # row is the whole edit; minting a version here would fill the
            # history with entries identical to their predecessors and make
            # the ones that matter harder to find.
            context = current or await self._services.current_context(service_id)
            if context is None:
                raise EntityNotFoundError("ServiceVersion", service_id)
            return ServiceSaved(service=service, context=context, version_minted=False)

        merged = _from_context(current)
        merged.update(versioned)
        name = merged.pop("name", service.name)

        if "name" in changes:
            service.name = changes["name"]

        version = await self._mint(
            service=service,
            company_id=company_id,
            name=str(name),
            configuration=merged,
            actor_user_id=actor_user_id,
            change_note=change_note,
        )
        return ServiceSaved(
            service=service, context=to_service_context(version), version_minted=True
        )

    async def archive(self, *, company_id: uuid.UUID, service_id: uuid.UUID) -> Service:
        """Soft-deletes a service.

        Its versions stay, and so do the conversations bound to them. A
        service is removed from the directory, never from history — a
        conversation that cannot say what it ran in is the failure this
        design exists to prevent.
        """
        service = await self.get(company_id=company_id, service_id=service_id)
        service.is_active = False
        from datetime import UTC, datetime

        service.deleted_at = datetime.now(UTC)
        return service

    async def _validate(self, *, company_id: uuid.UUID, configuration: dict[str, Any]) -> None:
        queue_id = configuration.get("logical_queue_id")
        if queue_id is not None:
            queue = await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)
            if queue is None or queue.company_id != company_id or queue.deleted_at is not None:
                raise InvalidServiceConfigurationError("That queue does not exist.")

        threshold = configuration.get("ai_confidence_threshold")
        if threshold is not None:
            try:
                value = Decimal(str(threshold))
            except (InvalidOperation, ValueError) as error:
                raise InvalidServiceConfigurationError(
                    "The confidence threshold must be a number."
                ) from error
            if not (Decimal("0") <= value <= Decimal("1")):
                raise InvalidServiceConfigurationError(
                    "The confidence threshold must be between 0 and 1."
                )

        for field in (
            "sla_queue_minutes",
            "sla_first_response_minutes",
            "sla_next_response_minutes",
            "sla_resolution_minutes",
            "ai_pickup_delay_seconds",
            "ai_resume_delay_seconds",
        ):
            value_or_none = configuration.get(field)
            # ``None`` is meaningful and different from 0 — "not measured"
            # versus "already breached the moment it starts" — so only a
            # value that is present is checked.
            if value_or_none is not None and int(value_or_none) < 0:
                raise InvalidServiceConfigurationError(f"'{field}' cannot be negative.")

    async def _mint(
        self,
        *,
        service: Service,
        company_id: uuid.UUID,
        name: str,
        configuration: dict[str, Any],
        actor_user_id: uuid.UUID | None,
        change_note: str | None,
    ) -> ServiceVersion:
        queue_name: str | None = None
        queue_id = configuration.get("logical_queue_id")
        if queue_id is not None:
            queue = await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)
            # Copied, not joined. A queue is renamed and soft-deleted through
            # the ordinary admin screen, and a version that lost its queue's
            # name would read "routed to 4f2a…" forever after.
            queue_name = queue.name if queue is not None else None

        version = await self._services.add_version(
            ServiceVersion(
                service_id=service.id,
                company_id=company_id,
                version=await self._services.next_version_number(service.id),
                name=name,
                logical_queue_id=queue_id,
                logical_queue_name=queue_name,
                overflow_strategy=OverflowStrategy(
                    configuration.get("overflow_strategy", OverflowStrategy.WAIT)
                ),
                ai_overflow_policy=AiOverflowPolicy(
                    configuration.get("ai_overflow_policy", AiOverflowPolicy.NEVER)
                ),
                sla_queue_minutes=configuration.get("sla_queue_minutes"),
                sla_first_response_minutes=configuration.get("sla_first_response_minutes"),
                sla_next_response_minutes=configuration.get("sla_next_response_minutes"),
                sla_resolution_minutes=configuration.get("sla_resolution_minutes"),
                ai_enabled=bool(configuration.get("ai_enabled", False)),
                ai_pickup_delay_seconds=int(configuration.get("ai_pickup_delay_seconds", 30)),
                ai_resume_delay_seconds=int(configuration.get("ai_resume_delay_seconds", 900)),
                ai_confidence_threshold=str(configuration.get("ai_confidence_threshold", "0.75")),
                extras=dict(configuration.get("extras") or {}),
                created_by_user_id=actor_user_id,
                change_note=change_note,
            )
        )
        # Promoted in the same transaction. A version written but never
        # pointed at would be invisible to every new conversation, which
        # reads as "my edit did nothing".
        service.current_version_id = version.id
        return version


def _from_context(context: ServiceContext) -> dict[str, Any]:
    """The current version as a plain mapping, ready to be merged over.

    An edit is expressed as a *change*, so the new version starts as a copy
    of the one it supersedes. Building it from the submitted fields alone
    would silently reset everything the caller did not mention.
    """
    return {
        "name": context.name,
        "logical_queue_id": context.queue.logical_queue_id if context.queue else None,
        "overflow_strategy": context.queue.overflow_strategy
        if context.queue
        else OverflowStrategy.WAIT,
        "ai_overflow_policy": context.queue.ai_overflow_policy
        if context.queue
        else AiOverflowPolicy.NEVER,
        "sla_queue_minutes": context.sla.queue_minutes,
        "sla_first_response_minutes": context.sla.first_response_minutes,
        "sla_next_response_minutes": context.sla.next_response_minutes,
        "sla_resolution_minutes": context.sla.resolution_minutes,
        "ai_enabled": context.ai.enabled,
        "ai_pickup_delay_seconds": context.ai.pickup_delay_seconds,
        "ai_resume_delay_seconds": context.ai.resume_delay_seconds,
        "ai_confidence_threshold": str(context.ai.confidence_threshold),
        "extras": dict(context.extras),
    }


__all__ = [
    "IDENTITY_FIELDS",
    "VERSIONED_FIELDS",
    "ServiceDirectoryService",
    "ServiceSaved",
]
