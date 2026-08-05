"""Giving every company a Service without changing what it experiences.

See ``docs/architecture/service-centric-migration.md`` — this is Stage 2.

**The governing rule, and everything here follows from it:** a seeded Service
carries the values a company *resolves to today*, never the model's defaults.
The migration copies the **effective** configuration, not the declared one.

That is not caution, it is the whole design. ``FallbackStage`` resolves to a
company's default service — or failing that, "the first service in the
directory" — and only answers ``NOT_CONFIGURED`` when a company has **no
active services at all**. So creating one Service is not additive: on the very
next inbound message it moves that company off every fallback simultaneously.
With stock defaults that would mean:

- ``AiPolicy.enabled`` is ``False``, so **AI silently switches off**
- ``SlaTargets()`` is all-``None``, so **clocks stop being measured**

Two outages dressed as a migration, neither raising an error, both discovered
by a customer. Seeding from resolved values is what makes the change a no-op.

**Dry run first, always.** ``plan()`` computes what would be written and
touches nothing; ``apply()`` takes a plan and writes it. No installation is
migrated before its plan reads as it should.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from blinkengage.application.services.configuration_resolver import ConfigurationResolver
from blinkengage.application.services.service_directory_service import ServiceDirectoryService
from blinkengage.domain.resolution import ConfigurationSource
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from blinkengage.infrastructure.database.models.company import Company
    from blinkengage.infrastructure.database.models.queue import Queue

#: The code a seeded service gets. Stable, so re-running finds its own work
#: rather than creating a second one beside it.
SEEDED_CODE_PREFIX = "general"

#: What a seeded Service says about itself on the Services screen.
#:
#: An administrator opening the directory the morning after a migration finds
#: something they did not create; it has to explain itself and say that it is
#: ordinary configuration they own.
SEEDED_DESCRIPTION = (
    "Created from this queue's existing configuration so nothing changed when "
    "Services were introduced. Rename, edit or replace it like any other."
)


@dataclass(frozen=True, slots=True)
class SeedPlan:
    """One Service that would be created, and the values it would carry.

    Every field is an *effective* value read through ``ConfigurationResolver``,
    so a reviewer can compare this against what the company runs on today and
    see that they match. A plan whose numbers surprise somebody is a plan that
    must not be applied.
    """

    company_id: uuid.UUID
    company_name: str
    queue_id: uuid.UUID
    queue_name: str
    code: str
    name: str

    ai_enabled: bool
    ai_pickup_delay_seconds: int
    ai_confidence_threshold: Decimal | None
    sla_first_response_minutes: int | None
    sla_resolution_minutes: int | None
    sla_queue_minutes: int | None
    sla_next_response_minutes: int | None

    #: Which tier supplied each value today. Carried so a reviewer can tell a
    #: figure the company chose from one the platform filled in — the second
    #: kind is what Stage 2 turns into a real choice.
    sources: dict[str, ConfigurationSource] = field(default_factory=dict)

    @property
    def is_company_default(self) -> bool:
        """Whether this becomes the company's default service.

        Exactly one plan per company is, and it is the one built from the
        queue the company's catch-all rule already points at — so
        ``FallbackStage`` resolves the same way routing already does rather
        than falling through to "the first service in display order", which
        is arbitrary for a company with several.
        """
        return self._default

    _default: bool = False


@dataclass(frozen=True, slots=True)
class SeedReport:
    """What a whole installation would get."""

    plans: tuple[SeedPlan, ...]
    #: Companies deliberately left alone, and why. Reported rather than
    #: silently skipped: "nothing happened to these" is the half of a
    #: migration report people forget to ask for and then need.
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def companies(self) -> int:
        return len({plan.company_id for plan in self.plans})


class ServiceSeeder:
    """Builds and applies Stage 2 plans.

    Deliberately split in two. ``plan`` is a pure read that any operator can
    run against production and inspect; ``apply`` performs exactly what a plan
    says and nothing it does not. A single method that decided and wrote at
    once could not be reviewed before it ran, which for a migration touching
    every tenant is the only review that matters.
    """

    def __init__(
        self,
        *,
        resolver: ConfigurationResolver,
        directory: ServiceDirectoryService | None = None,
        services: ServiceRepository | None = None,
        companies: CompanyRepository | None = None,
    ) -> None:
        self._resolver = resolver
        #: Absent for a dry run. ``apply`` refuses rather than silently doing
        #: nothing, so a caller cannot believe it migrated an installation it
        #: only planned.
        self._directory = directory
        self._services = services
        self._companies = companies

    async def apply(self, plans: list[SeedPlan]) -> list[uuid.UUID]:
        """Creates exactly what the plans describe, and nothing they do not.

        Separate from ``plan`` on purpose: a single method that decided and
        wrote at once could not be reviewed before it ran, and for a migration
        touching every tenant that is the only review that matters.

        **Idempotent by code.** A company that already has a Service with this
        code is skipped rather than given a second one, so a re-run after a
        partial failure completes the work instead of doubling it.

        **Sets the company default.** Without it ``FallbackStage`` resolves to
        whichever Service sorts first, which would make reordering the
        Services screen change routing.
        """
        if self._directory is None or self._companies is None or self._services is None:
            raise RuntimeError(
                "ServiceSeeder was built for planning only. Applying needs the "
                "service directory and company repositories — supply them, "
                "rather than letting a dry-run object write."
            )

        created: list[uuid.UUID] = []
        for plan in plans:
            existing = await self._services.by_code(company_id=plan.company_id, code=plan.code)
            if existing is not None:
                continue
            saved = await self._directory.create(
                company_id=plan.company_id,
                code=plan.code,
                name=plan.name,
                description=SEEDED_DESCRIPTION,
                logical_queue_id=plan.queue_id,
                sla_queue_minutes=plan.sla_queue_minutes,
                sla_first_response_minutes=plan.sla_first_response_minutes,
                sla_next_response_minutes=plan.sla_next_response_minutes,
                sla_resolution_minutes=plan.sla_resolution_minutes,
                ai_enabled=plan.ai_enabled,
                ai_pickup_delay_seconds=plan.ai_pickup_delay_seconds,
                ai_confidence_threshold=plan.ai_confidence_threshold,
            )
            created.append(saved.service.id)
            if plan.is_company_default:
                await self._set_default(company_id=plan.company_id, service_id=saved.service.id)
        return created

    async def _set_default(self, *, company_id: uuid.UUID, service_id: uuid.UUID) -> None:
        """Records which Service catches what nothing else claimed.

        Written through the settings dict rather than a column — see
        ``domain/company_settings.default_service_id`` for why it lives there.
        Rebuilt rather than mutated in place, because SQLAlchemy does not track
        changes inside a JSON value and an in-place edit would be silently
        dropped on flush.
        """
        company = await self._companies.get_by_id(company_id)  # type: ignore[union-attr]
        if company is None:
            return
        settings = dict(company.settings or {})
        services = dict(settings.get("services") or {})
        services["default_service_id"] = str(service_id)
        settings["services"] = services
        company.settings = settings

    async def plan_for_company(
        self, *, company: Company, queues: list[Queue], catch_all_queue_id: uuid.UUID | None
    ) -> list[SeedPlan]:
        """What this company would get. Reads only.

        One Service per **live** queue. Most companies have one, and a
        company with several gets a directory that mirrors the queues they
        already think in rather than a single Service that flattens them.
        """
        plans: list[SeedPlan] = []
        for index, queue in enumerate(queues):
            configuration = await self._resolver.for_conversation(
                company_id=company.id,
                queue_id=queue.id,
                # No service by definition — that is what makes this the
                # *effective* configuration this company runs on today.
                service=None,
                company=company,
            )
            targets = configuration.sla.value
            ai = configuration.ai
            plans.append(
                SeedPlan(
                    company_id=company.id,
                    company_name=company.name,
                    queue_id=queue.id,
                    queue_name=queue.name,
                    code=_code_for(queue.name, index),
                    name=queue.name,
                    # The company's *effective* AI state for this queue: the
                    # company switch and the queue's own opt-in, exactly as
                    # the Policy Engine reads them today.
                    ai_enabled=_ai_enabled_today(company, queue),
                    ai_pickup_delay_seconds=ai.pickup_delay_seconds.value,
                    # ``None`` on purpose where the company tier answered, so
                    # the company-wide setting keeps deciding rather than
                    # being frozen onto every service on the day of the
                    # migration.
                    ai_confidence_threshold=(
                        ai.confidence_threshold.value
                        if ai.confidence_threshold.source is ConfigurationSource.SERVICE
                        else None
                    ),
                    sla_first_response_minutes=targets.first_response_minutes,
                    sla_resolution_minutes=targets.resolution_minutes,
                    sla_queue_minutes=targets.queue_minutes,
                    sla_next_response_minutes=targets.next_response_minutes,
                    sources={
                        "sla": configuration.sla.source,
                        "ai_pickup_delay": ai.pickup_delay_seconds.source,
                        "ai_confidence_threshold": ai.confidence_threshold.source,
                    },
                    _default=queue.id == catch_all_queue_id,
                )
            )
        return plans


def _code_for(queue_name: str, index: int) -> str:
    """A stable, readable code derived from the queue it mirrors.

    Stable so a second run recognises its own work; readable because an
    administrator opening the Services screen the next morning should see
    something they recognise rather than a generated identifier.
    """
    slug = "".join(character if character.isalnum() else "-" for character in queue_name.lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or f"{SEEDED_CODE_PREFIX}-{index + 1}"


def _ai_enabled_today(company: Company, queue: Queue) -> bool:
    """Whether AI actually answers on this queue right now.

    Read from the two gates that decide it today — the company switch and the
    queue's opt-in — rather than from ``AiPolicy.enabled``'s default, which is
    ``False`` and would switch AI off for every company that uses it.

    Deliberately *not* asked of the Policy Engine. The policy also weighs
    conversation state and provider availability, which are facts about a
    moment rather than configuration, and a Service seeded from "AI was
    unavailable when the migration ran" would freeze an outage into
    configuration.
    """
    from blinkengage.domain.company_settings import is_ai_enabled, is_autopilot_enabled

    settings = company.settings or {}
    return is_ai_enabled(settings) and is_autopilot_enabled(settings) and queue.autopilot_enabled


__all__ = ["SEEDED_CODE_PREFIX", "SeedPlan", "SeedReport", "ServiceSeeder"]
