"""Stage 2 seeds Services from effective configuration, never from defaults.

This is the test that stands between the migration and two silent outages.

``FallbackStage`` only answers ``NOT_CONFIGURED`` when a company has **no
active services at all**. So the moment Stage 2 creates one, that company
moves off every fallback simultaneously — and with the model's own defaults
that means ``AiPolicy.enabled = False`` (AI switches off) and ``SlaTargets()``
all-``None`` (clocks stop). Neither raises. Both would be found by a customer.

So every test below is a *before equals after* assertion in disguise: the
seeded value must be the value the company was already running on.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from blinkengage.application.services.service_seeding import ServiceSeeder, _code_for
from blinkengage.domain.ai_policy import CompanyAiSettings, ResolvedAiPolicy, resolve_ai_policy
from blinkengage.domain.company_settings import default_service_id
from blinkengage.domain.resolution import ConfigurationSource, Resolved
from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import resolve_sla_targets

pytestmark = pytest.mark.asyncio


class _StubResolver:
    """Answers with whatever the company genuinely resolves to.

    A stub rather than a database, because what is under test is *what the
    seeder does with a resolved answer* — the resolution itself has its own
    tests, and going through Postgres here would test that twice and this
    once.
    """

    def __init__(self, *, sla: SlaTargets | None, company: CompanyAiSettings) -> None:
        self._sla = sla
        self._company = company

    async def for_conversation(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            sla=resolve_sla_targets(service=None, queue=self._sla),
            ai=resolve_ai_policy(service=None, company=self._company),
        )


def _company(**settings: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Blink Connected",
        settings={"ai": {"enabled": True, "autopilot": {"enabled": True}}, **settings},
    )


def _queue(*, name: str = "General", autopilot: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name=name, autopilot_enabled=autopilot)


async def _plan(company, queues, *, sla: SlaTargets | None, ai: CompanyAiSettings, default=None):
    seeder = ServiceSeeder(resolver=_StubResolver(sla=sla, company=ai))  # type: ignore[arg-type]
    return await seeder.plan_for_company(company=company, queues=queues, catch_all_queue_id=default)


class TestItNeverSilentlySwitchesAiOff:
    """The first of the two outages. ``AiPolicy.enabled`` defaults to
    ``False``; a company using AI must not be seeded with it."""

    async def test_a_company_using_ai_gets_a_service_with_ai_on(self) -> None:
        company = _company()
        plans = await _plan(
            company,
            [_queue(autopilot=True)],
            sla=SlaTargets(first_response_minutes=3),
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert plans[0].ai_enabled is True

    async def test_a_company_with_the_kill_switch_off_gets_a_service_with_ai_off(self) -> None:
        """Equally important in the other direction: seeding AI *on* for a
        company that switched it off would put AI-generated content in front
        of customers of a company that promised none."""
        company = _company(ai={"enabled": False, "autopilot": {"enabled": True}})
        plans = await _plan(
            company,
            [_queue(autopilot=True)],
            sla=None,
            ai=CompanyAiSettings(enabled=False, autopilot_enabled=True),
        )

        assert plans[0].ai_enabled is False

    async def test_a_queue_that_opted_out_stays_opted_out(self) -> None:
        company = _company()
        plans = await _plan(
            company,
            [_queue(autopilot=False)],
            sla=None,
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert plans[0].ai_enabled is False


class TestItNeverSilentlyStopsMeasuring:
    """The second outage. ``SlaTargets()`` is all-``None``; a company
    measuring 3/15 must be seeded with 3/15."""

    async def test_the_queues_targets_are_carried_onto_the_service(self) -> None:
        plans = await _plan(
            _company(),
            [_queue()],
            sla=SlaTargets(first_response_minutes=3, resolution_minutes=15),
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert plans[0].sla_first_response_minutes == 3
        assert plans[0].sla_resolution_minutes == 15
        assert plans[0].sources["sla"] is ConfigurationSource.QUEUE

    async def test_a_company_measuring_nothing_of_its_own_carries_the_platform_default(
        self,
    ) -> None:
        """Not ``None``. A company running on the platform default *is* being
        measured, and seeding blanks would stop that — the outage this whole
        class exists to prevent, arriving by a different door."""
        plans = await _plan(
            _company(),
            [_queue()],
            sla=None,
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert plans[0].sla_first_response_minutes is not None
        assert plans[0].sources["sla"] is ConfigurationSource.PLATFORM_DEFAULT


class TestThePickupDelayIsCarriedNotDefaulted:
    async def test_a_company_answering_instantly_keeps_answering_instantly(self) -> None:
        """The G1 transition, and the reason it is safe. A company resolving
        to ``0`` today is seeded with ``0`` — so retiring the platform tier
        afterwards changes nothing, which is the whole point."""
        plans = await _plan(
            _company(),
            [_queue()],
            sla=None,
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert plans[0].ai_pickup_delay_seconds == 0
        assert plans[0].sources["ai_pickup_delay"] is ConfigurationSource.PLATFORM_DEFAULT


class TestTheConfidenceThresholdIsNotFrozen:
    async def test_a_company_wide_threshold_is_left_to_the_company(self) -> None:
        """``None`` on the service, deliberately.

        Copying the company's number onto every Service would freeze it: an
        administrator later changing the company-wide threshold would find it
        ignored everywhere, because each Service now states one. The company
        tier must keep deciding until somebody chooses otherwise per service.
        """
        plans = await _plan(
            _company(),
            [_queue()],
            sla=None,
            ai=CompanyAiSettings(
                enabled=True, autopilot_enabled=True, confidence_threshold=Decimal("0.9")
            ),
        )

        assert plans[0].ai_confidence_threshold is None
        assert plans[0].sources["ai_confidence_threshold"] is ConfigurationSource.COMPANY


class TestTheDefaultServiceIsChosenNotGuessed:
    async def test_the_catch_all_queue_becomes_the_company_default(self) -> None:
        """``FallbackStage`` otherwise picks "the first service in display
        order", which is arbitrary for a company with several queues. Naming
        the one routing already falls through to keeps resolution and routing
        agreeing."""
        support, billing = _queue(name="Support"), _queue(name="Billing")
        plans = await _plan(
            _company(),
            [support, billing],
            sla=None,
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
            default=billing.id,
        )

        defaults = [plan for plan in plans if plan.is_company_default]
        assert len(defaults) == 1
        assert defaults[0].queue_name == "Billing"

    async def test_one_service_per_live_queue(self) -> None:
        plans = await _plan(
            _company(),
            [_queue(name="Support"), _queue(name="Billing"), _queue(name="Sales")],
            sla=None,
            ai=CompanyAiSettings(enabled=True, autopilot_enabled=True),
        )

        assert [plan.name for plan in plans] == ["Support", "Billing", "Sales"]


class TestTheCodeIsStableAndReadable:
    def test_it_mirrors_the_queue_an_administrator_already_knows(self) -> None:
        assert _code_for("Customer Support", 0) == "customer-support"

    def test_punctuation_and_spacing_collapse_rather_than_leaking(self) -> None:
        assert _code_for("Billing / Refunds", 0) == "billing-refunds"

    def test_a_queue_named_only_in_punctuation_still_gets_a_code(self) -> None:
        """A code is a key. Returning an empty string would make the seed
        fail on a unique constraint rather than on anything a person could
        act on."""
        assert _code_for("///", 2) == "general-3"


class TestTheResolvedShapeIsWhatTheSeederExpects:
    def test_a_resolved_policy_exposes_value_and_source(self) -> None:
        """Guards the seeder against the resolver changing shape underneath
        it — the plan reads ``.value`` and ``.source`` on every field."""
        policy = resolve_ai_policy(
            service=None, company=CompanyAiSettings(enabled=True, autopilot_enabled=True)
        )

        assert isinstance(policy, ResolvedAiPolicy)
        assert isinstance(policy.pickup_delay_seconds, Resolved)
        assert isinstance(policy.pickup_delay_seconds.source, ConfigurationSource)


class TestApplyRefusesToWriteFromADryRunObject:
    """A seeder built for planning must not silently do nothing.

    ``plan`` and ``apply`` are split so a migration can be reviewed before it
    runs. That split only protects anybody if calling ``apply`` on a
    planning-only object is loud — a silent no-op would let an operator
    believe an installation was migrated when it was untouched.
    """

    async def test_it_raises_rather_than_quietly_skipping(self) -> None:
        seeder = ServiceSeeder(
            resolver=_StubResolver(
                sla=None, company=CompanyAiSettings(enabled=True, autopilot_enabled=True)
            )  # type: ignore[arg-type]
        )

        with pytest.raises(RuntimeError, match="planning only"):
            await seeder.apply([])


class TestTheDefaultServiceSetting:
    """Where "which Service catches what nothing else claimed" is stored."""

    def test_a_company_that_has_chosen_none_reads_as_none(self) -> None:
        assert default_service_id({}) is None
        assert default_service_id({"services": {}}) is None

    def test_a_chosen_service_round_trips(self) -> None:
        chosen = uuid.uuid4()
        assert default_service_id({"services": {"default_service_id": str(chosen)}}) == chosen

    def test_a_malformed_value_costs_the_preference_and_never_the_conversation(self) -> None:
        """Resolution still works without a default — it falls through to the
        directory order. So a corrupted setting must degrade, not raise: a
        customer's message is not the right casualty for a bad JSON value."""
        for broken in ("not-a-uuid", 42, None, {"nested": "thing"}, []):
            assert default_service_id({"services": {"default_service_id": broken}}) is None

    def test_a_non_dict_section_does_not_crash_the_reader(self) -> None:
        assert default_service_id({"services": "corrupted"}) is None
