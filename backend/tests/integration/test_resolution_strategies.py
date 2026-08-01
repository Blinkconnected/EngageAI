"""The resolution strategies, against a real directory.

The pipeline's own guarantees are proven in ``tests/unit/test_service_resolution.py``.
These prove the strategies themselves decide the right thing — and, as much,
that they *record* why, because a routing decision nobody can read is the
black box this whole redesign exists to remove.

The one to look at is the keyword matching. Substring matching is the obvious
implementation and it silently misroutes: a service keyed on "count" swallows
"I can't access my account", and nobody reports it as a routing bug because
the conversation did arrive somewhere.
"""

import uuid
from typing import Any

import pytest

from blinkengage.application.services.resolution_strategies import (
    RULES_NAMESPACE,
    BusinessRulesStage,
    CustomerSelectionStage,
    FallbackStage,
    FixedServiceStage,
    default_stages,
)
from blinkengage.domain.service_resolution import (
    ResolutionRequest,
    ResolutionStrategy,
    StageOutcome,
    StageReason,
    resolve_service,
)
from blinkengage.infrastructure.database.models.service_directory import (
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
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


async def a_service(
    session: Any,
    company_id: uuid.UUID,
    name: str,
    *,
    rules: list[dict[str, Any]] | None = None,
    order: int = 0,
    active: bool = True,
) -> Service:
    services = ServiceRepository(session)
    service = await services.add(
        Service(
            company_id=company_id,
            code=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}",
            name=name,
            display_order=order,
            is_active=active,
        )
    )
    version = await services.add_version(
        ServiceVersion(
            service_id=service.id,
            company_id=company_id,
            version=1,
            name=name,
            extras={RULES_NAMESPACE: {"rules": rules}} if rules else {},
        )
    )
    service.current_version_id = version.id
    await session.flush()
    return service


def a_request(company_id: uuid.UUID, **kw: Any) -> ResolutionRequest:
    defaults: dict[str, Any] = {
        "company_id": company_id,
        "conversation_id": uuid.uuid4(),
        "channel_type": "whatsapp",
        "body": "hello",
        "customer_id": None,
    }
    return ResolutionRequest(**{**defaults, **kw})


@pytest.mark.asyncio
class TestTheCustomerIsNotSecondGuessed:
    async def test_a_chosen_service_wins(self, app: Any) -> None:
        """A customer who picked "Billing" has stated what they want.
        Anything overriding that is the platform telling somebody they are
        wrong about their own problem."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            billing = await a_service(session, company_id, "Billing")
            await session.commit()

            result = await CustomerSelectionStage(ServiceRepository(session)).resolve(
                a_request(company_id, customer_selected_service_id=billing.id)
            )

        assert result.outcome is StageOutcome.RESOLVED
        assert result.reason is StageReason.CUSTOMER_CHOSE
        assert result.service_id == billing.id

    async def test_nothing_chosen_is_not_a_miss(self, app: Any) -> None:
        """A conversation that never offered a menu has not had a customer
        decline to use it. Recording that as "no match" would make the
        Inspector report a decision nobody was asked to make."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await session.commit()

            result = await CustomerSelectionStage(ServiceRepository(session)).resolve(
                a_request(company_id)
            )

        assert result.outcome is StageOutcome.SKIPPED
        assert result.reason is StageReason.PRECONDITION_UNMET

    async def test_a_choice_of_another_companys_service_is_refused(self, app: Any) -> None:
        """Tenant isolation at the routing layer. Recorded rather than
        silently dropped, because it means something upstream is wrong."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            ours = await a_company(session)
            theirs = await a_company(session)
            other = await a_service(session, theirs, "Their Billing")
            await session.commit()

            result = await CustomerSelectionStage(ServiceRepository(session)).resolve(
                a_request(ours, customer_selected_service_id=other.id)
            )

        assert result.outcome is StageOutcome.CONTINUE
        assert result.service_id is None
        assert "another company" in result.evidence["note"]

    async def test_a_choice_of_a_switched_off_service_continues(self, app: Any) -> None:
        """The intent is no longer actionable, but somebody still needs
        answering — so the pipeline carries on rather than rejecting."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            gone = await a_service(session, company_id, "Retired", active=False)
            await session.commit()

            result = await CustomerSelectionStage(ServiceRepository(session)).resolve(
                a_request(company_id, customer_selected_service_id=gone.id)
            )

        assert result.outcome is StageOutcome.CONTINUE
        assert result.reason is StageReason.NO_MATCH


@pytest.mark.asyncio
class TestBusinessRules:
    async def test_a_keyword_routes_to_its_service(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            billing = await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["invoice", "refund"]}]
            )
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, body="I have a question about my invoice")
            )

        assert result.outcome is StageOutcome.RESOLVED
        assert result.service_id == billing.id
        assert result.evidence["matched_keyword"] == "invoice"

    async def test_a_keyword_does_not_match_inside_another_word(self, app: Any) -> None:
        """The trap. Substring matching is the obvious implementation and it
        misroutes silently — a service keyed on "count" swallowing "I can't
        access my account" arrives *somewhere*, so nobody reports it."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await a_service(session, company_id, "Counting", rules=[{"keywords": ["count"]}])
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, body="I cannot access my account")
            )

        assert result.outcome is StageOutcome.CONTINUE
        assert result.reason is StageReason.NO_MATCH

    async def test_a_multi_word_keyword_matches_as_a_phrase(self, app: Any) -> None:
        """What somebody typing "payment failed" intends."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            billing = await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["payment failed"]}]
            )
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, body="my payment failed yesterday")
            )

        assert result.service_id == billing.id

    async def test_a_channel_rule_routes_without_any_text(self, app: Any) -> None:
        """ "WhatsApp goes to Sales" must work for a customer who sent a
        photo and no words."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            sales = await a_service(
                session, company_id, "Sales", rules=[{"channels": ["whatsapp"]}]
            )
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, body=None, channel_type="whatsapp")
            )

        assert result.service_id == sales.id
        assert result.evidence["matched_channel"] == "whatsapp"

    async def test_a_channel_rule_ignores_other_channels(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await a_service(session, company_id, "Sales", rules=[{"channels": ["whatsapp"]}])
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, channel_type="email")
            )

        assert result.outcome is StageOutcome.CONTINUE

    async def test_rules_are_evaluated_in_the_operators_order(self, app: Any) -> None:
        """Order is the only priority mechanism. A separate priority number
        that disagrees with the visible order is a bug report waiting to
        happen."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            first = await a_service(
                session, company_id, "Urgent", rules=[{"keywords": ["invoice"]}], order=1
            )
            await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["invoice"]}], order=2
            )
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id, body="about my invoice")
            )

        assert result.service_id == first.id

    async def test_no_rules_is_skipped_not_a_miss(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await a_service(session, company_id, "Support")
            await session.commit()

            result = await BusinessRulesStage(ServiceRepository(session)).resolve(
                a_request(company_id)
            )

        assert result.outcome is StageOutcome.SKIPPED
        assert result.reason is StageReason.NOT_CONFIGURED

    async def test_a_malformed_rule_set_does_not_take_routing_down(self, app: Any) -> None:
        """Stored JSON is not typed. A bad write must not stop every
        conversation for the company."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            services = ServiceRepository(session)
            service = await services.add(
                Service(company_id=company_id, code="broken", name="Broken")
            )
            version = await services.add_version(
                ServiceVersion(
                    service_id=service.id,
                    company_id=company_id,
                    version=1,
                    name="Broken",
                    extras={RULES_NAMESPACE: {"rules": "not-a-list"}},
                )
            )
            service.current_version_id = version.id
            await session.commit()

            result = await BusinessRulesStage(services).resolve(a_request(company_id))

        assert result.outcome is StageOutcome.SKIPPED


@pytest.mark.asyncio
class TestFixedAndFallback:
    async def test_one_active_service_resolves_without_asking_anybody(self, app: Any) -> None:
        """The common case at signup. A directory with one entry should
        never be shown to a customer as a choice."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            only = await a_service(session, company_id, "Support")
            await session.commit()

            result = await FixedServiceStage(ServiceRepository(session)).resolve(
                a_request(company_id)
            )

        assert result.service_id == only.id
        assert result.reason is StageReason.FIXED

    async def test_several_services_is_ambiguous_and_skipped(self, app: Any) -> None:
        """Picking one would be a guess presented as a decision."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await a_service(session, company_id, "Sales")
            await a_service(session, company_id, "Support")
            await session.commit()

            result = await FixedServiceStage(ServiceRepository(session)).resolve(
                a_request(company_id)
            )

        assert result.outcome is StageOutcome.SKIPPED
        assert result.evidence["active_services"] == 2

    async def test_the_fallback_says_it_fell_back(self, app: Any) -> None:
        """It resolves the same service a fixed stage might, and reports a
        different reason, because the two mean different things to somebody
        reading the Inspector: one is a decision, the other is nothing
        having decided."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            first = await a_service(session, company_id, "Sales", order=1)
            await a_service(session, company_id, "Support", order=2)
            await session.commit()

            result = await FallbackStage(ServiceRepository(session)).resolve(a_request(company_id))

        assert result.service_id == first.id
        assert result.reason is StageReason.FALLBACK

    async def test_a_company_with_no_services_is_answered_honestly(self, app: Any) -> None:
        """Not invented. The conversation is handled the way it was before
        services existed, and the Inspector says why."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await session.commit()

            result = await FallbackStage(ServiceRepository(session)).resolve(a_request(company_id))

        assert result.outcome is StageOutcome.CONTINUE
        assert result.reason is StageReason.NOT_CONFIGURED


@pytest.mark.asyncio
class TestThePipelineEndToEnd:
    async def test_every_stage_is_recorded_not_only_the_winner(self, app: Any) -> None:
        """The explainability requirement. "Why did this go to Billing?" is
        answered by what the earlier stages did *not* do as much as by what
        the winner did."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            billing = await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["invoice"]}], order=1
            )
            await a_service(session, company_id, "Support", order=2)
            await session.commit()

            resolved = await resolve_service(
                default_stages(ServiceRepository(session)),
                a_request(company_id, body="about my invoice"),
            )

        assert resolved.service_id == billing.id
        strategies = [stage.strategy for stage in resolved.stages]
        assert strategies == [
            ResolutionStrategy.CUSTOMER_SELECTION,
            ResolutionStrategy.BUSINESS_RULES,
        ]
        assert resolved.stages[0].outcome is StageOutcome.SKIPPED

    async def test_a_conversation_always_lands_somewhere(self, app: Any) -> None:
        """A conversation resolving to no service has no SLA, no queue and
        no owner — a customer waiting in a room the platform does not know
        exists. Nothing matched here, and it still lands."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id = await a_company(session)
            await a_service(session, company_id, "Sales", order=1)
            await a_service(session, company_id, "Support", order=2)
            await session.commit()

            resolved = await resolve_service(
                default_stages(ServiceRepository(session)),
                a_request(company_id, body="something nothing matches"),
            )

        assert resolved.service_id is not None
        assert resolved.stages[-1].reason is StageReason.FALLBACK
