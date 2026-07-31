"""A score nobody is allowed to hand out.

Certification is only worth having if it cannot be gamed and cannot be
faked, so most of this file is about the ways a scoring function usually
*is* both. The arithmetic is four lines and could be read; what needs
asserting is the judgement around it.

Three rules carry the weight:

- What a connector never claimed does not count against it, or every honest
  manifest scores worse than a dishonest one.
- What was not executed does not count *for* it, or a suite that runs nothing
  certifies everything.
- Nothing here may message a real customer to prove that it can.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from blinkengage.domain.connector_certification import (
    EMITS_TO_A_CUSTOMER,
    MINIMUM_COVERAGE,
    MUTATES_THE_CHANNEL,
    SCENARIO_FEATURE,
    Certification,
    Compatibility,
    Grade,
    Outcome,
    ScenarioKind,
    ScenarioResult,
    certify,
    supports_scenario,
)
from blinkengage.domain.connector_lifecycle import ChannelFeature, Direction


def results(**counts: int) -> tuple[ScenarioResult, ...]:
    """A run with a given shape, kinds assigned arbitrarily.

    Which scenario produced which outcome does not affect the score, and
    pretending otherwise in a fixture would suggest it did.
    """
    kinds = iter(list(ScenarioKind) * 4)
    return tuple(
        ScenarioResult(kind=next(kinds), outcome=Outcome(name))
        for name, count in counts.items()
        for _ in range(count)
    )


class TestWhatIsNotClaimedIsNotCountedAgainstYou:
    def test_a_connector_that_cannot_do_something_is_not_marked_down(self) -> None:
        """The rule the whole design rests on. SMS cannot send media.
        Scoring that as a failure would make every honest manifest score
        worse than a dishonest one, and within a week every connector would
        claim everything."""
        honest = certify(results(**{"pass": 5, "not_supported": 6}))

        assert honest.percent == 100
        assert honest.grade is Grade.PRODUCTION_READY

    def test_claiming_more_does_not_buy_a_better_score(self) -> None:
        """The other direction, and the reason the denominator is what the
        connector claimed: declaring a feature buys you a scenario that has
        to pass, not credit for having declared it."""
        modest = certify(results(**{"pass": 5, "not_supported": 6}))
        boastful = certify(results(**{"pass": 5, "fail": 6}))

        assert modest.percent == 100
        assert boastful.percent < 50
        assert boastful.grade is Grade.NOT_READY

    def test_not_supported_does_not_inflate_coverage_either(self) -> None:
        """Otherwise a connector could reach full coverage by claiming
        nothing, which is the same loophole from the other side."""
        assert certify(results(**{"pass": 2, "not_supported": 9})).coverage == 1.0
        assert certify(results(**{"pass": 2, "skipped": 9})).coverage < 0.3


class TestWhatWasNotRunDoesNotCountForYou:
    def test_a_suite_that_ran_almost_nothing_is_inconclusive(self) -> None:
        """"96%, Production Ready" from two executed scenarios is a sentence
        no suite should be able to produce."""
        thin = certify(results(**{"pass": 2, "skipped": 9}))

        assert thin.percent == 100
        assert thin.coverage < MINIMUM_COVERAGE
        assert thin.grade is Grade.INCONCLUSIVE

    def test_a_suite_that_ran_nothing_at_all_is_inconclusive(self) -> None:
        assert certify(()).grade is Grade.INCONCLUSIVE
        assert certify(results(not_supported=11)).grade is Grade.INCONCLUSIVE

    def test_a_connector_claiming_nothing_is_not_scored_zero(self) -> None:
        """Web Chat legitimately has almost nothing to prove against a
        provider. Not a pass, and not a failure — and saying so is more
        useful than a 0% that reads as broken."""
        nothing = certify(results(not_supported=11))

        assert nothing.grade is Grade.INCONCLUSIVE
        assert nothing.failed == 0


class TestAFailureIsAFailure:
    def test_one_broken_thing_keeps_it_out_of_production(self) -> None:
        """Nine passes and a broken authentication is not a 90% channel, it
        is a channel that does not work. The arithmetic alone would have
        called it production ready."""
        mostly_fine = certify(results(**{"pass": 9, "fail": 1}))

        assert mostly_fine.percent == 90
        assert mostly_fine.grade is not Grade.PRODUCTION_READY
        assert mostly_fine.grade is Grade.NEEDS_ATTENTION

    def test_many_failures_are_not_ready(self) -> None:
        assert certify(results(**{"pass": 4, "fail": 6})).grade is Grade.NOT_READY

    def test_a_clean_run_certifies(self) -> None:
        assert certify(results(**{"pass": 10})).grade is Grade.PRODUCTION_READY


class TestWarningsCountPartially:
    def test_a_warning_is_worth_less_than_a_pass(self) -> None:
        """A connector that always warns should not certify identically to
        one that never does — and should still beat one that fails, because
        it did the thing."""
        clean = certify(results(**{"pass": 10}))
        warned = certify(results(**{"warning": 10}))
        broken = certify(results(fail=10))

        assert broken.score < warned.score < clean.score

    def test_warnings_alone_do_not_reach_production(self) -> None:
        assert certify(results(**{"warning": 10})).grade is not Grade.PRODUCTION_READY


class TestTheScoreCannotBeAssigned:
    def test_certification_has_no_way_in_but_certify(self) -> None:
        """A certification that could be handed out is a certification that
        means whatever the person handing it out wanted."""
        certification = certify(results(**{"pass": 5}))

        with pytest.raises((AttributeError, TypeError)):
            certification.score = 1.0  # type: ignore[misc]
        with pytest.raises((AttributeError, TypeError)):
            certification.grade = Grade.PRODUCTION_READY  # type: ignore[misc]

    def test_the_grade_always_follows_the_numbers(self) -> None:
        """Constructed directly, the fields are whatever was passed — so the
        guarantee has to be that ``certify`` is the only producer, and that
        it is deterministic."""
        for shape in (
            {"pass": 10},
            {"pass": 9, "fail": 1},
            {"pass": 2, "skipped": 9},
            {"warning": 10},
        ):
            first = certify(results(**shape))
            second = certify(results(**shape))
            assert first == second

    def test_the_counts_add_up_to_the_run(self) -> None:
        """A report whose parts do not sum to its whole is a report somebody
        has edited."""
        run = results(**{"pass": 3, "fail": 2, "warning": 1, "skipped": 2, "not_supported": 3})
        c = certify(run)

        assert c.passed + c.failed + c.warned + c.skipped + c.not_supported == len(run)


class TestScenariosComeFromTheFeatureMatrix:
    """The suite must not be a second declaration of what a connector
    supports — the manifest already said."""

    def test_direction_decides_which_media_scenario_applies(self) -> None:
        """The exact case ``Direction`` was added for: a connector that
        receives media and cannot send it claims download and not upload, so
        upload reports NOT_SUPPORTED rather than failing."""
        inbound_only = ((ChannelFeature.MEDIA, Direction.INBOUND),)

        assert supports_scenario(ScenarioKind.MEDIA_DOWNLOAD, inbound_only)
        assert not supports_scenario(ScenarioKind.MEDIA_UPLOAD, inbound_only)

    def test_both_covers_both(self) -> None:
        both = ((ChannelFeature.MEDIA, Direction.BOTH),)

        assert supports_scenario(ScenarioKind.MEDIA_UPLOAD, both)
        assert supports_scenario(ScenarioKind.MEDIA_DOWNLOAD, both)

    def test_lifecycle_scenarios_apply_to_everyone(self) -> None:
        """Authentication, disconnect and reconnect are not features — they
        are what every connector has by existing, so nothing has to declare
        them to be tested on them."""
        for kind in (
            ScenarioKind.AUTHENTICATION,
            ScenarioKind.DISCONNECT,
            ScenarioKind.RECONNECT,
            ScenarioKind.WEBHOOK_DELIVERY,
        ):
            assert supports_scenario(kind, ())

    def test_every_feature_backed_scenario_names_a_real_feature(self) -> None:
        for feature, direction in SCENARIO_FEATURE.values():
            assert isinstance(feature, ChannelFeature)
            assert isinstance(direction, Direction)


class TestNothingMessagesARealCustomer:
    def test_everything_that_emits_is_declared(self) -> None:
        """A certification run must never be the reason somebody's customer
        receives a message. Anything that would put something in front of a
        person is listed, and the runner skips it without a target."""
        assert ScenarioKind.SEND_MESSAGE in EMITS_TO_A_CUSTOMER
        assert ScenarioKind.MEDIA_UPLOAD in EMITS_TO_A_CUSTOMER
        assert ScenarioKind.TYPING_INDICATOR in EMITS_TO_A_CUSTOMER
        assert ScenarioKind.READ_RECEIPT in EMITS_TO_A_CUSTOMER

    def test_reading_scenarios_are_not_gated(self) -> None:
        """The guard has to be narrow or it becomes the reason nobody runs
        the suite. Receiving and downloading observe; they do not emit."""
        assert ScenarioKind.RECEIVE_MESSAGE not in EMITS_TO_A_CUSTOMER
        assert ScenarioKind.MEDIA_DOWNLOAD not in EMITS_TO_A_CUSTOMER
        assert ScenarioKind.AUTHENTICATION not in EMITS_TO_A_CUSTOMER

    def test_everything_that_changes_the_channel_is_declared(self) -> None:
        """Off by default from the other direction: a run that left a working
        channel disconnected would be a diagnostic worse than the problem."""
        assert frozenset(
            {
                ScenarioKind.DISCONNECT,
                ScenarioKind.RECONNECT,
                ScenarioKind.TOKEN_REFRESH,
            }
        ) == MUTATES_THE_CHANNEL

    def test_no_scenario_is_both(self) -> None:
        """A scenario needing two different opt-ins is one whose guard
        somebody will get wrong."""
        assert not (EMITS_TO_A_CUSTOMER & MUTATES_THE_CHANNEL)


class TestCompatibility:
    def test_an_expiry_within_the_window_is_flagged(self) -> None:
        """Ninety days, because a provider API deprecation is a migration and
        finding out the week it happens is finding out too late."""
        compat = Compatibility(
            platform_version="1.0.0",
            connector_version="1.0.0",
            provider_api_version="v21.0",
            supported_until=date(2026, 9, 1),
        )

        assert compat.expiring_within(90, today=date(2026, 7, 31))
        assert not compat.expiring_within(10, today=date(2026, 7, 31))

    def test_no_published_schedule_is_never_expiring(self) -> None:
        """Telegram's Bot API has no such concept. ``None`` says so rather
        than inventing a date, and must not read as "expires today"."""
        compat = Compatibility(
            platform_version="1.0.0",
            connector_version="1.0.0",
            provider_api_version="unversioned",
        )

        assert not compat.expiring_within(3650, today=date(2026, 7, 31))

    def test_never_verified_is_distinguishable_from_verified_long_ago(self) -> None:
        """Different next actions: one needs a first run, the other needs a
        fresh one."""
        never = Compatibility("1.0.0", "1.0.0", "v21.0")
        once = Compatibility(
            "1.0.0", "1.0.0", "v21.0", last_verified=datetime(2026, 1, 1, tzinfo=UTC)
        )

        assert never.last_verified is None
        assert once.last_verified is not None


class TestScenarioResults:
    def test_only_executed_outcomes_count_as_executed(self) -> None:
        for outcome in (Outcome.PASS, Outcome.FAIL, Outcome.WARNING):
            assert ScenarioResult(ScenarioKind.AUTHENTICATION, outcome).executed
        for outcome in (Outcome.SKIPPED, Outcome.NOT_SUPPORTED):
            assert not ScenarioResult(ScenarioKind.AUTHENTICATION, outcome).executed

    def test_a_result_carries_its_own_duration(self) -> None:
        """A connector that passes slowly is visibly different from one that
        passes."""
        assert ScenarioResult(ScenarioKind.AUTHENTICATION, Outcome.PASS, 420).duration_ms == 420

    def test_an_unexecuted_scenario_took_no_time(self) -> None:
        assert ScenarioResult(ScenarioKind.SEND_MESSAGE, Outcome.SKIPPED).duration_ms == 0


class TestPercentIsHonest:
    @pytest.mark.parametrize(
        ("shape", "expected"),
        [
            ({"pass": 10}, 100),
            ({"pass": 9, "fail": 1}, 90),
            ({"pass": 1, "fail": 1}, 50),
            ({"warning": 2}, 50),
            ({"fail": 3}, 0),
        ],
    )
    def test_the_number_matches_the_run(self, shape: dict, expected: int) -> None:
        assert certify(results(**shape)).percent == expected

    def test_a_certification_is_comparable(self) -> None:
        """Frozen and value-equal, so two runs of the same shape are the same
        certification — which is what makes "did this get worse?" answerable."""
        assert isinstance(certify(results(**{"pass": 1})), Certification)
        assert certify(results(**{"pass": 1})) == certify(results(**{"pass": 1}))


class TestNoConnectorEmitsWithoutATarget:
    """The runner guards this, and every connector guards it again.

    Not redundancy — the runner's guard is one caller away from an
    irreversible provider call, and one connector already dropped its own
    copy and went to the wire with an empty recipient, minting a reusable
    attachment on a customer's Page before the recipient was consulted.
    """

    @pytest.mark.parametrize(
        "channel_type", ["telegram", "email", "sms", "whatsapp", "messenger", "instagram"]
    )
    async def test_an_emitting_scenario_without_a_target_does_not_call_out(
        self, channel_type: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        from blinkengage.domain.connector import DeploymentContext
        from blinkengage.infrastructure.connectors import ConnectorRegistry

        connector = ConnectorRegistry.get(channel_type)
        assert connector is not None

        reached: list[str] = []

        async def refuse(self: object, *args: object, **kwargs: object) -> None:
            reached.append(str(args[:2]))
            raise httpx.ConnectError("no network in this test")

        monkeypatch.setattr(httpx.AsyncClient, "request", refuse, raising=False)
        monkeypatch.setattr(httpx.AsyncClient, "send", refuse, raising=False)

        for kind in EMITS_TO_A_CUSTOMER:
            await connector.run_scenario(
                kind,
                credentials={"access_token": "t", "bot_token": "1:x", "page_id": "p"},
                context=DeploymentContext("https://engage.example.com"),
                target=None,
            )

        assert reached == [], f"{channel_type} went to the wire with no target"


class TestTheRunnerBoundsAScenario:
    async def test_a_hanging_connector_does_not_hang_the_suite(self) -> None:
        """``SCENARIO_TIMEOUT`` was defined, documented, exported — and never
        applied. One connector hanging hung the whole run, on a screen
        somebody is watching."""
        import asyncio

        from blinkengage.application.services import connector_certification_service
        from blinkengage.application.services.connector_certification_service import (
            ConnectorCertificationService,
        )
        from blinkengage.domain.connector import DeploymentContext

        monkey = connector_certification_service
        original = monkey.SCENARIO_TIMEOUT
        monkey.SCENARIO_TIMEOUT = 0.05
        try:

            class Hangs:
                channel_type = "telegram"

                async def run_scenario(self, *args: object, **kwargs: object) -> None:
                    await asyncio.sleep(10)

            service = ConnectorCertificationService(
                context=DeploymentContext("https://engage.example.com")
            )
            result = await service._one(  # noqa: SLF001 - the guard under test
                Hangs(),  # type: ignore[arg-type]
                ScenarioKind.AUTHENTICATION,
                declared=(),
                credentials={},
                target=None,
                include_mutating=False,
                channel=type("C", (), {"webhook_secret": None})(),  # type: ignore[arg-type]
                callback_url=None,
            )
        finally:
            monkey.SCENARIO_TIMEOUT = original

        # Skipped, not failed: a scenario that ran out of time was not
        # measured, and a timeout is not evidence the connector is broken.
        assert result.outcome is Outcome.SKIPPED
        assert result.detail_key == "certification.skipped.timedOut"
