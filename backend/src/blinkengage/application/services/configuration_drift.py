"""Finding configuration that is set but no longer obeyed.

See ``docs/architecture/service-centric-migration.md`` — this is Stage 3's
drift check.

During compatibility mode the Service is the writer and the queue's own
configuration is still readable. That combination has one failure mode, and it
is silent: an administrator edits a queue's response-time targets, the screen
saves, and nothing changes — because a Service owns that queue and the Service
wins. Nobody gets an error. The promise the company believes it made is not
the promise the platform is measuring.

**This job finds that and reports it. It never corrects it.** A divergence
means somebody reached legacy configuration through a path that should no
longer exist; overwriting the value would destroy the evidence of *how*, and
the how is the actual bug. The queue keeps its value, the report names it, and
a person decides.

**Scope, and why it is this narrow.** The queue tier only ever carried one
fact worth comparing: SLA targets, either as its legacy minute columns or as
an attached ``SlaPolicy``. The other tiered facts have no queue tier to
disagree with —

- ``ai.pickup_delay_seconds`` resolves Service → platform default. No queue
  ever stored one.
- ``ai.confidence_threshold`` resolves Service → company, and a service
  shadowing a company-wide threshold is the documented design rather than
  drift (see ``AiPolicy.confidence_threshold``).
- The queue's Autopilot opt-in *is* a genuine queue-tier value with a service
  equivalent, but whether AI may engage is a ``Policy.AI_ENGAGEMENT``
  decision needing a conversation to evaluate against, not a resolvable
  configuration value. Comparing it here would mean reading
  ``Queue.autopilot_enabled`` directly, which is the second configuration
  path this whole migration exists to remove. It stays out until the policy
  can be asked a question about a queue rather than a conversation.

So: one comparison, done properly, through ``ConfigurationResolver`` — the
only thing any of this is allowed to read configuration from.

The report also counts what Stage 3 and Stage 4 need in order to end:
companies with no Service at all (Stage 3's exit criterion is zero), and
queues still carrying legacy SLA config whether or not it disagrees (Stage 4
cannot drop those columns while the number is above zero).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from blinkengage.application.services.configuration_resolver import ConfigurationResolver
from blinkengage.domain.resolution import ConfigurationSource
from blinkengage.domain.service_context import ServiceContext, SlaTargets
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from blinkengage.infrastructure.database.models.company import Company
    from blinkengage.infrastructure.database.models.queue import Queue
    from blinkengage.infrastructure.database.models.service_directory import Service

#: ``list_for_company`` is paginated for the API. The scan wants all of them,
#: and a company with more queues than this has a different problem.
_EVERY_QUEUE = 1000


@dataclass(frozen=True, slots=True)
class Drift:
    """One queue whose configuration is set and not obeyed.

    Carries the names as well as the ids because this is read by a person
    deciding whether somebody made a mistake, and "queue 8a487bb6 disagrees
    with service 3facc23c" is not a sentence anybody can act on.
    """

    company_id: uuid.UUID
    company_name: str
    service_id: uuid.UUID
    service_name: str
    queue_id: uuid.UUID
    queue_name: str
    #: What actually applies, and what the queue would have said. Rendered
    #: rather than structured: the report exists to be read.
    applied: str
    ignored: str

    def describe(self) -> str:
        # ``queue_name`` comes from the live queue row rather than from the
        # name the service version copied, and is never blank. That is right
        # for this report specifically: a service version carries the queue's
        # name as a value so it can explain a *past* conversation after a
        # rename, but drift is a statement about configuration as it stands
        # now, and the name to act on is the one on the screen today.
        return (
            f"{self.company_name}: queue {self.queue_name!r} still sets {self.ignored}, "
            f"but service {self.service_name!r} owns it and applies {self.applied}"
        )


@dataclass(frozen=True, slots=True)
class DriftReport:
    """What one scan found."""

    companies_checked: int
    #: Stage 3 ends when this is empty. Carried as (id, name) rather than a
    #: count because the next question is always "which ones".
    companies_without_a_service: tuple[tuple[uuid.UUID, str], ...]
    #: Queues whose legacy SLA config is still populated, agreeing or not.
    #: Stage 4 cannot drop those columns while this is above zero.
    queues_carrying_legacy_sla: int
    drifts: tuple[Drift, ...]

    @property
    def is_clean(self) -> bool:
        """Whether Stage 3's exit criterion is met on this scan.

        Legacy SLA config that *agrees* is not drift — it is Stage 4's
        problem, not a bug — so it deliberately does not make a scan dirty.
        """
        return not self.drifts and not self.companies_without_a_service


class ConfigurationDriftDetector:
    """Reads twice and compares. Writes nothing, ever.

    The absence of a write path is the point rather than an omission: a
    detector that could correct what it found would eventually be asked to,
    and the correction would erase the only evidence of which screen let
    somebody set a value the platform ignores.
    """

    def __init__(
        self,
        *,
        resolver: ConfigurationResolver,
        services: ServiceRepository,
        queues: QueueRepository,
    ) -> None:
        self._resolver = resolver
        self._services = services
        #: Used to *enumerate* queues, never to read configuration off one —
        #: every value compared below comes back through the resolver. The
        #: distinction is the whole point of the migration: which queues
        #: exist is a fact about the installation, what a queue promises is
        #: configuration and has exactly one reader.
        self._queues = queues

    async def scan(self, companies: list[Company]) -> DriftReport:
        without: list[tuple[uuid.UUID, str]] = []
        drifts: list[Drift] = []
        legacy = 0

        for company in companies:
            active = await self._services.active_for_company(company.id)
            if not active:
                without.append((company.id, company.name))

            owners = await self._owners_by_queue(active)

            # Every live queue, not only the ones a service owns. The count
            # below is Stage 4's readiness number — "can we drop the legacy
            # columns yet?" — and scoping it to serviced queues would report
            # zero for a company that has not been migrated at all. A zero
            # that means "nothing examined" is worse than no number, because
            # it reads exactly like "nothing to clean up".
            for queue in await self._live_queues(company.id):
                alone = await self._resolver.for_conversation(
                    company_id=company.id, queue_id=queue.id, service=None, company=company
                )
                if alone.sla.source is not ConfigurationSource.QUEUE:
                    # The queue configures no SLA of its own, so there is no
                    # legacy value here to be ignored or to migrate.
                    continue

                legacy += 1
                owner = owners.get(queue.id)
                if owner is None:
                    # Unowned: the queue's own targets are what applies, which
                    # is the correct answer rather than a shadowed one.
                    continue

                service, context = owner
                applied = await self._resolver.for_conversation(
                    company_id=company.id, queue_id=queue.id, service=context, company=company
                )
                if applied.sla.source is not ConfigurationSource.SERVICE:
                    # The service defines no targets and defers to the queue.
                    # Correct behaviour — and the case that would fire on
                    # every Stage 2 company if this compared values without
                    # first asking which tier won.
                    continue
                if applied.sla.value == alone.sla.value:
                    continue

                drifts.append(
                    Drift(
                        company_id=company.id,
                        company_name=company.name,
                        service_id=service.id,
                        service_name=context.name,
                        queue_id=queue.id,
                        queue_name=queue.name,
                        applied=_describe(applied.sla.value),
                        ignored=_describe(alone.sla.value),
                    )
                )

        return DriftReport(
            companies_checked=len(companies),
            companies_without_a_service=tuple(without),
            queues_carrying_legacy_sla=legacy,
            drifts=tuple(drifts),
        )

    async def _owners_by_queue(
        self, services: list[Service]
    ) -> dict[uuid.UUID, tuple[Service, ServiceContext]]:
        """Which service owns which queue.

        A service naming no queue does not own one — its conversations reach
        a queue through the rules, and that queue's SLA is then the honest
        answer rather than a shadowed one.
        """
        owners: dict[uuid.UUID, tuple[Service, ServiceContext]] = {}
        for service in services:
            context = await self._services.current_context(service.id)
            if context is not None and context.queue is not None:
                owners[context.queue.logical_queue_id] = (service, context)
        return owners

    async def _live_queues(self, company_id: uuid.UUID) -> list[Queue]:
        queues, _ = await self._queues.list_for_company(
            company_id=company_id, offset=0, limit=_EVERY_QUEUE
        )
        return queues


def _describe(targets: SlaTargets) -> str:
    """The clocks a tier sets, as a person would say them.

    Only the ones it actually measures. Listing the unset clocks as "None"
    would make two tiers that differ in one target look wholly different, and
    the reader has to spot which one moved.
    """
    parts = [
        f"{label} {value}m"
        for label, value in (
            ("queue", targets.queue_minutes),
            ("first response", targets.first_response_minutes),
            ("next response", targets.next_response_minutes),
            ("resolution", targets.resolution_minutes),
        )
        if value is not None
    ]
    return ", ".join(parts) if parts else "nothing"


__all__ = ["ConfigurationDriftDetector", "Drift", "DriftReport"]
