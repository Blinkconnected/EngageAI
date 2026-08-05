"""The drift check, against real companies, services and queues.

The defect this exists to catch is silent by construction: an administrator
edits a queue's response-time targets, the screen saves, and the platform goes
on measuring the service's. So the test that matters is not "the detector
runs" — it is that a queue and a service holding *different* numbers is
reported, and that the three ways of holding the *same* numbers are not.

Written as integration rather than unit tests on purpose. The comparison is
two passes through ``ConfigurationResolver``, and a resolver stubbed to return
what the test already assumes would prove nothing about which tier really
wins.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.configuration_drift import ConfigurationDriftDetector
from blinkengage.application.services.configuration_resolver import ConfigurationResolver
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.service_directory import ServiceVersion
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository
from tests.integration.test_routing_explainability import _archive_every_service, _queue
from tests.integration.test_service_resolution_ingest import a_service

pytestmark = pytest.mark.asyncio


async def _scan(session: Any) -> Any:
    companies = list((await session.execute(select(Company))).scalars().all())
    return await ConfigurationDriftDetector(
        resolver=ConfigurationResolver(
            queues=QueueRepository(session), policies=SlaPolicyRepository(session)
        ),
        services=ServiceRepository(session),
        queues=QueueRepository(session),
    ).scan(companies)


async def _queue_promises(session: Any, queue_id: uuid.UUID, *, first_response: int | None) -> None:
    """Sets the queue's legacy minute target directly.

    Deliberately not through the API: after Stage 3c that route is closed,
    and the whole point of the check is to find values written by a path that
    should no longer exist. Reaching for the column is what an old migration,
    a script or a stale client does.
    """
    queue = await session.get(Queue, queue_id)
    queue.first_response_target_minutes = first_response
    await session.flush()


async def _a_service_owning(
    session: Any, company_id: uuid.UUID, name: str, *, queue_id: uuid.UUID, queue_name: str
) -> Any:
    """A service owning a queue, the way the real create writes one.

    ``ServiceDirectoryService`` copies the queue's name onto the version
    rather than joining to it, so a version whose queue is later renamed or
    deleted still explains itself. The shared ``a_service`` helper predates
    that and leaves it blank; a drift report built on it would be testing a
    degraded case while claiming to test the ordinary one.
    """
    service = await a_service(session, company_id, name, queue_id=queue_id)
    version = await _version_of(session, service.id)
    version.logical_queue_name = queue_name
    await session.flush()
    return service


async def _version_of(session: Any, service_id: uuid.UUID) -> Any:
    return (
        (
            await session.execute(
                select(ServiceVersion).where(ServiceVersion.service_id == service_id)
            )
        )
        .scalars()
        .one()
    )


async def _blank_the_services_sla(session: Any, service_id: uuid.UUID) -> None:
    """Leaves the service defining no targets at all, so it defers."""
    version = await _version_of(session, service_id)
    version.sla_first_response_minutes = None
    version.sla_queue_minutes = None
    version.sla_next_response_minutes = None
    version.sla_resolution_minutes = None
    await session.flush()


class TestADisagreementIsReported:
    async def test_a_queue_whose_targets_are_ignored_is_named(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The defect, exactly: the queue says 45 minutes, the service says
        15, and the platform measures 15 while nobody is told."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            # ``_a_service_owning`` sets a 15-minute first-response target.
            await _a_service_owning(
                session, company_id, "Support", queue_id=queue_id, queue_name="Support queue"
            )
            await _queue_promises(session, queue_id, first_response=45)
            await session.commit()

            found = await _scan(session)

        assert len(found.drifts) == 1
        drift = found.drifts[0]
        assert drift.queue_name == "Support queue"
        assert drift.service_name == "Support"
        assert "first response 15m" in drift.applied
        assert "first response 45m" in drift.ignored
        assert not found.is_clean

    async def test_the_report_reads_as_a_sentence(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Read by a person deciding whether somebody made a mistake. Two
        UUIDs and the word "drift" is not something anybody can act on."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _a_service_owning(
                session, company_id, "Support", queue_id=queue_id, queue_name="Support queue"
            )
            await _queue_promises(session, queue_id, first_response=45)
            await session.commit()

            found = await _scan(session)

        sentence = found.drifts[0].describe()
        assert "Support queue" in sentence
        assert "first response 45m" in sentence
        assert "first response 15m" in sentence

    async def test_the_queue_is_named_even_when_the_service_version_is_not(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The name comes from the queue, not from the service's copy of it.

        A version stores the queue's name as a value so it can explain a past
        conversation after a rename, and one written when the lookup found
        nothing stores a blank. Drift is a statement about configuration as it
        stands *now*, so the report reads the live row — and stays actionable
        for a service whose copy is empty.
        """
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            # ``a_service`` copies no queue name, which is what the real
            # create writes when its lookup comes back empty.
            await a_service(session, company_id, "Support", queue_id=queue_id)
            await _queue_promises(session, queue_id, first_response=45)
            await session.commit()

            found = await _scan(session)

        assert found.drifts[0].queue_name == "Support queue"
        assert "Support queue" in found.drifts[0].describe()


class TestAgreementIsNotDrift:
    async def test_matching_targets_are_left_alone(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Legacy configuration that agrees is Stage 4's problem — a column
        to drop — not a bug to report. Reporting it would bury the real
        divergences under every company that has not been cleaned up yet."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support", queue_id=queue_id)
            await _queue_promises(session, queue_id, first_response=15)
            await session.commit()

            found = await _scan(session)

        assert found.drifts == ()
        # Still counted, because Stage 4 cannot drop the column while any
        # queue is populated — agreeing or not.
        assert found.queues_carrying_legacy_sla == 1

    async def test_a_queue_that_configures_nothing_is_not_drift(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """No legacy value means nothing is being ignored."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support", queue_id=queue_id)
            await _queue_promises(session, queue_id, first_response=None)
            await session.commit()

            found = await _scan(session)

        assert found.drifts == ()
        assert found.queues_carrying_legacy_sla == 0

    async def test_a_service_that_defers_to_the_queue_is_not_drift(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A service defining no targets *is* deferring to the queue, so the
        queue's numbers are what applies. Correct behaviour — and the case
        that would fire on every Stage 2 company if the check compared values
        without first asking which tier won."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            service = await a_service(session, company_id, "Support", queue_id=queue_id)
            await _blank_the_services_sla(session, service.id)
            await _queue_promises(session, queue_id, first_response=45)
            await session.commit()

            found = await _scan(session)

        assert found.drifts == ()


class TestTheLegacyCountIsHonest:
    """Stage 4's readiness number, and the zero it must never report.

    Found by running the first version of this scan against production: it
    counted only queues a service owned, so an installation where nothing had
    been migrated reported ``queues_carrying_legacy_sla: 0``. That reads
    exactly like "nothing left to clean up" and meant "nothing examined".
    """

    async def test_a_company_with_no_services_still_has_its_queues_counted(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        await _archive_every_service(client, owner_headers)
        queue_id = uuid.UUID(await _queue(client, owner_headers, name="Support queue"))

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _queue_promises(session, queue_id, first_response=45)
            await session.commit()

            found = await _scan(session)

        assert found.queues_carrying_legacy_sla >= 1
        # Nothing shadows it, so it is not drift — just work Stage 4 has left.
        assert found.drifts == ()


class TestTheStageThreeExitCriterion:
    async def test_a_company_with_no_service_is_named(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Stage 3 ends when this list is empty, so the platform measures it
        rather than somebody checking by hand before a release."""
        await _archive_every_service(client, owner_headers)

        factory = app.state.container.session_factory()
        async with factory() as session:
            found = await _scan(session)

        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        assert company_id in [row[0] for row in found.companies_without_a_service]
        assert not found.is_clean

    async def test_a_registered_company_already_has_one(
        self, registered_owner: dict, app: Any
    ) -> None:
        """Stage 3a's half of the criterion: registration seeds a service, so
        a company created from here on never joins that list."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            found = await _scan(session)

        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        assert company_id not in [row[0] for row in found.companies_without_a_service]


class TestItNeverWrites:
    async def test_the_detector_has_no_write_path(self) -> None:
        """Guarded rather than trusted. A detector that could correct what it
        found would eventually be asked to, and the correction would erase
        the evidence of which screen let somebody set an ignored value."""
        import ast
        import inspect

        from blinkengage.application.services import configuration_drift

        tree = ast.parse(inspect.getsource(configuration_drift))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not called & {"add", "commit", "flush", "delete", "merge", "execute"}, (
            "the drift detector reached for a write. It reports; it does not "
            "correct — see its module docstring for why that is deliberate."
        )
