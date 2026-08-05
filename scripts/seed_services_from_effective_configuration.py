"""Stage 2 of the service-centric migration: give every company a Service.

See ``docs/architecture/service-centric-migration.md``.

Every company gets one Service per live queue, seeded from the configuration
it **resolves to today** — not from the model's defaults. That distinction is
the whole migration, because ``FallbackStage`` only answers ``NOT_CONFIGURED``
while a company has *no active services at all*. The moment one exists, that
company moves off every fallback simultaneously, and with stock defaults that
would mean:

- ``AiPolicy.enabled`` is ``False``, so **AI silently switches off**
- ``SlaTargets()`` is all-``None``, so **SLA clocks stop being measured**

Two outages dressed as a migration, neither raising an error, both found by a
customer rather than by us. Seeding from resolved values is what makes the
change a no-op the day it runs.

**Dry run is the default.** With no arguments this reports what it would
write and touches nothing. Nothing is migrated before its report reads the way
somebody expects.

    # what would happen
    docker compose exec backend python scripts/seed_services_from_effective_configuration.py

    # do it
    docker compose exec backend python scripts/seed_services_from_effective_configuration.py --apply

Idempotent: a company that already has a Service with the seeded code is left
alone, so a re-run after a partial failure finishes the work rather than
doubling it. A company that already has *any* active Service is skipped
entirely — they have made decisions this must not overwrite.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from blinkengage.application.services.configuration_resolver import ConfigurationResolver
from blinkengage.application.services.service_directory_service import ServiceDirectoryService
from blinkengage.application.services.service_seeding import SeedPlan, ServiceSeeder
from blinkengage.core.config import get_settings
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.queue import Queue, RoutingRule
from blinkengage.infrastructure.database.session import create_engine, create_session_factory
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository


async def _catch_all_queue_id(session, company_id: uuid.UUID) -> uuid.UUID | None:
    """The queue the company's catch-all rule already points at.

    That Service becomes the company default, so resolution falls through the
    same way routing already does. Without it ``FallbackStage`` picks whichever
    Service sorts first — which would mean reordering the Services screen
    changes which Service catches unclaimed conversations.
    """
    rows = (
        (
            await session.execute(
                select(RoutingRule)
                .where(RoutingRule.company_id == company_id, RoutingRule.is_active)
                .order_by(RoutingRule.priority.desc())
            )
        )
        .scalars()
        .all()
    )
    for rule in rows:
        if rule.conditions in ({}, None):
            return rule.target_queue_id
    return None


async def _live_queues(session, company_id: uuid.UUID) -> list[Queue]:
    return list(
        (
            await session.execute(
                select(Queue)
                .where(
                    Queue.company_id == company_id,
                    Queue.deleted_at.is_(None),
                    Queue.is_active,
                )
                .order_by(Queue.created_at)
            )
        )
        .scalars()
        .all()
    )


def _describe(plan: SeedPlan) -> str:
    ai = "on" if plan.ai_enabled else "off"
    sla = f"{plan.sla_first_response_minutes or '—'}/{plan.sla_resolution_minutes or '—'} min"
    default = "  [company default]" if plan.is_company_default else ""
    return (
        f"    {plan.code:<24} queue={plan.queue_name:<20} "
        f"AI {ai:<3} delay {plan.ai_pickup_delay_seconds}s  SLA {sla}"
        f"  (sla from {plan.sources['sla'].value}){default}"
    )


async def main(apply: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    planned = 0
    skipped: list[tuple[str, str]] = []
    try:
        async with factory() as session:
            companies = list(
                (
                    await session.execute(
                        select(Company)
                        .where(Company.deleted_at.is_(None))
                        .order_by(Company.created_at)
                    )
                )
                .scalars()
                .all()
            )
            services = ServiceRepository(session)
            resolver = ConfigurationResolver(
                queues=QueueRepository(session), policies=SlaPolicyRepository(session)
            )
            seeder = ServiceSeeder(
                resolver=resolver,
                directory=ServiceDirectoryService(
                    services=services, queues=QueueRepository(session)
                )
                if apply
                else None,
                services=services if apply else None,
                companies=CompanyRepository(session) if apply else None,
            )

            for company in companies:
                if await services.active_for_company(company.id):
                    # They have made their own decisions. A migration that
                    # overwrote them would be the opposite of preserving
                    # effective configuration.
                    skipped.append((company.name, "already has an active service"))
                    continue

                queues = await _live_queues(session, company.id)
                if not queues:
                    skipped.append((company.name, "no live queue to build a service from"))
                    continue

                plans = await seeder.plan_for_company(
                    company=company,
                    queues=queues,
                    catch_all_queue_id=await _catch_all_queue_id(session, company.id),
                )
                planned += len(plans)
                print(f"  {company.name}")
                for plan in plans:
                    print(_describe(plan))

                if apply:
                    await seeder.apply(plans)

            if apply:
                await session.commit()
    finally:
        await engine.dispose()

    print()
    print(f"{'Created' if apply else 'Would create'} {planned} service(s).")
    if skipped:
        print(f"Skipped {len(skipped)}:")
        for name, why in skipped:
            print(f"    {name}: {why}")
    if not apply:
        print()
        print("Dry run — nothing was written. Re-run with --apply to migrate.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the services. Without this the run reports and changes nothing.",
    )
    sys.exit(asyncio.run(main(parser.parse_args().apply)))
