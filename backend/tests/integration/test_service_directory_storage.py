"""The Service Directory, against a real database.

The domain tests prove the *rules*. These prove the rules survive contact
with storage — which is where versioning designs usually come apart:

- a version is minted when something routing-relevant moves, and **not**
  when a name is corrected. Get that wrong in the lenient direction and every
  customer accumulates a version per conversation, which is the same as no
  versioning at all;
- a conversation bound to a version keeps reading it after the service is
  edited, renamed, or switched off;
- a rebinding is a new row, so "why did this conversation move?" still has
  an answer afterwards.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from blinkengage.domain.customer_context import ContactPreference, CustomerTier
from blinkengage.domain.service_context import ContextBindingReason
from blinkengage.infrastructure.database.models.service_directory import (
    ConversationContextBinding,
    CustomerContextVersion,
    RuntimeQueue,
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    CustomerContextRepository,
    RuntimeQueueRepository,
    ServiceRepository,
)


async def a_company(session: Any) -> uuid.UUID:
    from blinkengage.infrastructure.database.models.company import Company, CompanyStatus

    company = Company(
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        status=CompanyStatus.ACTIVE,
        billing_currency="JOD",
    )
    session.add(company)
    await session.flush()
    return company.id


async def a_customer(session: Any, company_id: uuid.UUID) -> uuid.UUID:
    from blinkengage.infrastructure.database.models.customer import Customer

    customer = Customer(company_id=company_id, full_name="Acme Trading")
    session.add(customer)
    await session.flush()
    return customer.id


async def a_service_with_version(
    session: Any, company_id: uuid.UUID, **version_kw: Any
) -> tuple[Service, ServiceVersion]:
    services = ServiceRepository(session)
    service = await services.add(
        Service(company_id=company_id, code=f"svc-{uuid.uuid4().hex[:6]}", name="Support")
    )
    version = await services.add_version(
        ServiceVersion(
            service_id=service.id,
            company_id=company_id,
            version=await services.next_version_number(service.id),
            name=version_kw.pop("name", "Support"),
            **version_kw,
        )
    )
    service.current_version_id = version.id
    await session.flush()
    return service, version


@pytest.mark.asyncio
class TestAConversationKeepsWhatItStartedWith:
    async def test_editing_a_service_does_not_move_a_bound_conversation(
        self, app: Any
    ) -> None:
        """The guarantee, through storage. An administrator halving the
        first-response target at noon must not rewrite the deadline of a
        conversation opened that morning."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            service, v1 = await a_service_with_version(
                session, company_id, sla_first_response_minutes=60
            )
            services = ServiceRepository(session)

            # The administrator edits: a *new* version, not an overwrite.
            v2 = await services.add_version(
                ServiceVersion(
                    service_id=service.id,
                    company_id=company_id,
                    version=await services.next_version_number(service.id),
                    name="Support",
                    sla_first_response_minutes=30,
                )
            )
            service.current_version_id = v2.id
            await session.commit()

            bound = await services.context_for_version(v1.id)
            current = await services.current_context(service.id)

        assert bound is not None and bound.sla.first_response_minutes == 60
        assert current is not None and current.sla.first_response_minutes == 30

    async def test_a_renamed_service_can_still_say_what_it_was(self, app: Any) -> None:
        """The name is carried by value on the version. A service renamed or
        archived must not leave a running conversation unable to say what it
        is running in."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            service, version = await a_service_with_version(
                session, company_id, name="Billing Support"
            )
            service.name = "Finance"
            await session.commit()

            context = await ServiceRepository(session).context_for_version(version.id)

        assert context is not None
        assert context.name == "Billing Support"

    async def test_version_numbers_start_at_one_and_increment(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            service, first = await a_service_with_version(session, company_id)
            services = ServiceRepository(session)
            second = await services.add_version(
                ServiceVersion(
                    service_id=service.id,
                    company_id=company_id,
                    version=await services.next_version_number(service.id),
                    name="Support",
                )
            )
            await session.commit()

        assert (first.version, second.version) == (1, 2)


@pytest.mark.asyncio
class TestCustomerVersionsAreMintedOnlyWhenTheyShould:
    async def test_a_rename_does_not_mint_a_version(self, app: Any) -> None:
        """The one that keeps the table readable.

        A customer record changes constantly — a CRM sync writing a field
        back, an agent fixing a typo. If each of those minted a version there
        would be one per conversation, a chain nobody can read, and no
        versioning in any useful sense.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            customer_id = await a_customer(session, company_id)
            customers = CustomerContextRepository(session)

            first = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme Trading"
            )
            second = await customers.ensure_version(
                customer_id=customer_id,
                company_id=company_id,
                display_name="ACME Trading LLC",
            )
            await session.commit()

            rows = (
                (
                    await session.execute(
                        select(CustomerContextVersion).where(
                            CustomerContextVersion.customer_id == customer_id
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert first.id == second.id
        assert len(rows) == 1

    async def test_a_vip_promotion_does_mint_one(self, app: Any) -> None:
        """The other direction. If this did not fork the history, the
        upgrade would never take effect for anybody's next conversation."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            customer_id = await a_customer(session, company_id)
            customers = CustomerContextRepository(session)

            before = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme"
            )
            after = await customers.ensure_version(
                customer_id=customer_id,
                company_id=company_id,
                display_name="Acme",
                tier=CustomerTier.VIP,
            )
            await session.commit()

        assert before.id != after.id
        assert (before.version, after.version) == (1, 2)
        assert after.tier is CustomerTier.VIP

    async def test_returning_to_a_previous_state_reuses_that_version(
        self, app: Any
    ) -> None:
        """Promoted then demoted reuses the original version rather than
        minting a third identical one. Matched on the fingerprint, not only
        against the newest row."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            customer_id = await a_customer(session, company_id)
            customers = CustomerContextRepository(session)

            standard = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme"
            )
            await customers.ensure_version(
                customer_id=customer_id,
                company_id=company_id,
                display_name="Acme",
                tier=CustomerTier.VIP,
            )
            back = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme"
            )
            await session.commit()

        assert back.id == standard.id

    async def test_the_stored_context_reports_whether_it_is_still_current(
        self, app: Any
    ) -> None:
        """The fingerprint travels with the context, so the console can
        answer "why is this conversation not being treated as VIP?" without
        a second query."""
        from blinkengage.domain.customer_context import matches

        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            customer_id = await a_customer(session, company_id)
            customers = CustomerContextRepository(session)
            version = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme"
            )
            await session.commit()

            context = await customers.context_for_version(version.id)

        assert context is not None
        assert matches(context, version.fingerprint) is True
        assert matches(context, "a-different-fingerprint") is False

    async def test_a_preference_change_mints_a_version(self, app: Any) -> None:
        """Opting out of automated messages changes how every future
        conversation is handled, so it has to fork."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            customer_id = await a_customer(session, company_id)
            customers = CustomerContextRepository(session)

            before = await customers.ensure_version(
                customer_id=customer_id, company_id=company_id, display_name="Acme"
            )
            after = await customers.ensure_version(
                customer_id=customer_id,
                company_id=company_id,
                display_name="Acme",
                contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES,
            )
            await session.commit()

        assert before.id != after.id


@pytest.mark.asyncio
class TestBindingsAreAHistoryNotAPointer:
    async def test_the_current_binding_is_the_newest_one(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            _, version = await a_service_with_version(session, company_id)
            conversation_id = await a_conversation(session, company_id)
            bindings = ContextBindingRepository(session)

            await bindings.add(
                ConversationContextBinding(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    service_version_id=version.id,
                    reason=ContextBindingReason.BOUND_AT_START,
                )
            )
            await session.commit()

            current = await bindings.current(conversation_id)

        assert current is not None
        assert current.reason is ContextBindingReason.BOUND_AT_START

    async def test_rebinding_keeps_the_original(self, app: Any) -> None:
        """"Moved to another service on the 3rd, by Sara, because the
        customer reached the wrong team" is the question this table exists
        to answer. Overwriting would erase it."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            _, first = await a_service_with_version(session, company_id)
            _, second = await a_service_with_version(session, company_id)
            conversation_id = await a_conversation(session, company_id)
            bindings = ContextBindingRepository(session)

            await bindings.add(
                ConversationContextBinding(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    service_version_id=first.id,
                    reason=ContextBindingReason.BOUND_AT_START,
                )
            )
            await bindings.add(
                ConversationContextBinding(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    service_version_id=second.id,
                    reason=ContextBindingReason.REROUTED_TO_ANOTHER_SERVICE,
                    note="Reached the wrong team",
                )
            )
            await session.commit()

            history = await bindings.history(conversation_id)
            current = await bindings.current(conversation_id)

        assert len(history) == 2
        assert history[0].service_version_id == first.id
        assert current is not None
        assert current.service_version_id == second.id
        assert current.note == "Reached the wrong team"


@pytest.mark.asyncio
class TestRuntimeLanes:
    async def test_a_logical_queue_holds_several_lanes(self, app: Any) -> None:
        """The split the queue architecture rests on. Without it, "the
        support queue is full" cannot be answered: full for whom?"""
        from blinkengage.domain.runtime_queues import RuntimeQueueKind

        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            queue_id = await a_queue(session, company_id)
            lanes = RuntimeQueueRepository(session)

            await lanes.add(
                RuntimeQueue(
                    company_id=company_id,
                    logical_queue_id=queue_id,
                    kind=RuntimeQueueKind.WAITING,
                    capacity=50,
                )
            )
            await lanes.add(
                RuntimeQueue(
                    company_id=company_id,
                    logical_queue_id=queue_id,
                    kind=RuntimeQueueKind.VIP,
                    # Zero means unlimited, not closed — a VIP is never told
                    # the lane is full.
                    capacity=0,
                )
            )
            await session.commit()

            found = await lanes.lanes_for(queue_id)

        assert {lane.kind for lane in found} == {RuntimeQueueKind.WAITING, RuntimeQueueKind.VIP}
        assert {lane.capacity for lane in found} == {50, 0}


async def a_conversation(session: Any, company_id: uuid.UUID) -> uuid.UUID:
    from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
    from blinkengage.infrastructure.database.models.conversation import (
        Conversation,
        ConversationStatus,
    )

    channel = ChannelConfig(
        company_id=company_id, channel_type="whatsapp", display_name="WhatsApp"
    )
    session.add(channel)
    await session.flush()

    conversation = Conversation(
        company_id=company_id,
        customer_id=await a_customer(session, company_id),
        channel_config_id=channel.id,
        status=ConversationStatus.WAITING,
    )
    session.add(conversation)
    await session.flush()
    return conversation.id


async def a_queue(session: Any, company_id: uuid.UUID) -> uuid.UUID:
    from blinkengage.infrastructure.database.models.queue import Queue

    queue = Queue(company_id=company_id, name=f"Support {uuid.uuid4().hex[:6]}")
    session.add(queue)
    await session.flush()
    return queue.id
