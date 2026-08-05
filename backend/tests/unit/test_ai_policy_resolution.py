"""What AI may do here, and which tier said so.

The rule these test used to be three: a service→company resolver for the
confidence threshold, a hard-coded ``0`` in the ingest consumer for the pickup
delay, and five inline conditions deciding whether AI could engage at all on
the path that had no service. Three answers to one question, and the one a
reader got depended on which module they opened.

So the tests below are as much about **provenance** as about values. A resolved
answer that is right but reports the wrong tier is still a defect: it is what
makes "why is this conversation waiting thirty seconds" answerable a month
later, when the service has been edited twice since.
"""

from decimal import Decimal

from blinkengage.domain.ai_policy import (
    PLATFORM_DEFAULT_ACTIVITY_WINDOW_SECONDS,
    PLATFORM_DEFAULT_CONFIDENCE_THRESHOLD,
    PLATFORM_DEFAULT_OUT_OF_HOURS_ACTIVITY_WINDOW_SECONDS,
    PLATFORM_DEFAULT_PICKUP_DELAY_SECONDS,
    CompanyAiSettings,
    effective_activity_window,
    effective_pickup_delay,
    resolve_ai_policy,
)
from blinkengage.domain.resolution import ConfigurationSource
from blinkengage.domain.service_context import AiPolicy

_COMPANY_ON = CompanyAiSettings(enabled=True, autopilot_enabled=True)
_COMPANY_OFF = CompanyAiSettings(enabled=False, autopilot_enabled=True)


def _resolve(service: AiPolicy | None = None, *, company=_COMPANY_ON):
    return resolve_ai_policy(service=service, company=company)


class TestItResolvesSettingsAndNotPermission:
    """Whether AI *may* act is ``Policy.AI_ENGAGEMENT``'s decision.

    This module once carried an ``enabled`` of its own, resolved from a subset
    of the facts the policy weighs. Two answers to one question, and they would
    have diverged the first time a policy gained a condition. Policies decide;
    resolvers supply the numbers they decide with.
    """

    def test_there_is_no_enabled_to_disagree_with_the_policy(self) -> None:
        resolved = _resolve(AiPolicy(enabled=True))

        assert not hasattr(resolved, "enabled")
        assert not hasattr(resolved, "may_engage")

    def test_settings_resolve_the_same_whether_or_not_ai_is_switched_on(self) -> None:
        """A switched-off service still has a delay and a threshold. Refusing
        to resolve them would make the Inspector unable to explain what *would*
        have applied, which is what an administrator turning AI on wants to
        know before they do it."""
        off = _resolve(AiPolicy(enabled=False, pickup_delay_seconds=45))
        on = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=45))

        assert off.pickup_delay_seconds == on.pickup_delay_seconds


class TestThePickupDelay:
    def test_the_service_wins(self) -> None:
        resolved = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=45))

        assert resolved.pickup_delay_seconds.value == 45
        assert resolved.pickup_delay_seconds.source is ConfigurationSource.SERVICE

    def test_without_a_service_the_platform_answers_and_admits_it(self) -> None:
        """It used to be a hard-coded ``0`` in the ingest consumer — a
        fallback nobody had chosen, in a branch nobody could see. It is still
        zero, and now it is a *stated* platform default with a reason
        attached: how long a conversation may sit before somebody accepts it
        is a promise a business makes, not one the platform may make for it.
        """
        resolved = _resolve()

        assert resolved.pickup_delay_seconds.value == PLATFORM_DEFAULT_PICKUP_DELAY_SECONDS
        assert resolved.pickup_delay_seconds.source is ConfigurationSource.PLATFORM_DEFAULT

    def test_zero_from_a_service_is_a_choice_and_survives(self) -> None:
        """The falsy-value trap. A service that deliberately set ``0`` — an
        FAQ line where waiting only makes the customer wait — must not have it
        read as "unset" and replaced from the tier below."""
        resolved = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=0))

        assert resolved.pickup_delay_seconds.value == 0
        assert resolved.pickup_delay_seconds.source is ConfigurationSource.SERVICE


class TestBusinessHoursInvertTheDelay:
    def test_inside_hours_the_delay_applies(self) -> None:
        resolved = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=30))

        assert effective_pickup_delay(resolved, within_business_hours=True).value == 30

    def test_outside_hours_it_collapses_to_zero(self) -> None:
        """The delay exists to give a human first refusal. At 03:00 there is
        nobody to defer to, and thirty seconds of deliberate silence serves
        nobody."""
        resolved = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=30))

        assert effective_pickup_delay(resolved, within_business_hours=False).value == 0

    def test_and_the_provenance_survives_the_adjustment(self) -> None:
        """Still the service's delay, adjusted by the calendar. Reporting it
        as a platform default would lose who set it."""
        resolved = _resolve(AiPolicy(enabled=True, pickup_delay_seconds=30))
        adjusted = effective_pickup_delay(resolved, within_business_hours=False)

        assert adjusted.source is ConfigurationSource.SERVICE

    def test_it_adjusts_the_delay_and_nothing_else(self) -> None:
        """Business hours never *enable* AI — that is the policy's call. This
        only changes how long an already-permitted AI waits."""
        resolved = _resolve(AiPolicy(enabled=False, pickup_delay_seconds=30))

        assert effective_pickup_delay(resolved, within_business_hours=False).value == 0


class TestTheConfidenceThreshold:
    def test_service_then_company_then_platform(self) -> None:
        with_service = _resolve(AiPolicy(enabled=True, confidence_threshold=Decimal("0.9")))
        assert with_service.confidence_threshold.value == Decimal("0.9")
        assert with_service.confidence_threshold.source is ConfigurationSource.SERVICE

        company = CompanyAiSettings(
            enabled=True, autopilot_enabled=True, confidence_threshold=Decimal("0.6")
        )
        from_company = _resolve(AiPolicy(enabled=True), company=company)
        assert from_company.confidence_threshold.value == Decimal("0.6")
        assert from_company.confidence_threshold.source is ConfigurationSource.COMPANY

        from_platform = _resolve(AiPolicy(enabled=True))
        assert from_platform.confidence_threshold.value == PLATFORM_DEFAULT_CONFIDENCE_THRESHOLD
        assert from_platform.confidence_threshold.source is ConfigurationSource.PLATFORM_DEFAULT

    def test_a_service_that_defines_none_does_not_lower_a_bar_the_company_raised(self) -> None:
        """The defect this rule was written for. A company that deliberately
        set 0.9 must not have it replaced by a service default the moment
        somebody creates a service."""
        company = CompanyAiSettings(
            enabled=True, autopilot_enabled=True, confidence_threshold=Decimal("0.9")
        )
        resolved = _resolve(AiPolicy(enabled=True, confidence_threshold=None), company=company)

        assert resolved.confidence_threshold.value == Decimal("0.9")


class TestTheActivityWindow:
    def test_inside_hours_is_short_and_outside_is_long(self) -> None:
        """A human is expected during the day, so a stale message is theirs.
        At night nobody is coming, so a message from the small hours is still
        worth an automated answer in the morning."""
        inside = effective_activity_window(service_window_seconds=None, within_business_hours=True)
        outside = effective_activity_window(
            service_window_seconds=None, within_business_hours=False
        )

        assert inside.value == PLATFORM_DEFAULT_ACTIVITY_WINDOW_SECONDS
        assert outside.value == PLATFORM_DEFAULT_OUT_OF_HOURS_ACTIVITY_WINDOW_SECONDS
        assert outside.value > inside.value

    def test_a_service_may_set_its_own(self) -> None:
        resolved = effective_activity_window(service_window_seconds=120, within_business_hours=True)

        assert resolved.value == 120
        assert resolved.source is ConfigurationSource.SERVICE

    def test_the_window_is_selected_by_now_not_by_arrival(self) -> None:
        """Stated as a property rather than a scenario: the function takes the
        business-hours state as an argument and has no way to know when the
        message arrived. That is the design — a message landing at 23:00 under
        the twelve-hour window is judged against the one-hour window at 09:00,
        because by then humans were available and chose not to answer it.
        """
        overnight = effective_activity_window(
            service_window_seconds=None, within_business_hours=False
        )
        next_morning = effective_activity_window(
            service_window_seconds=None, within_business_hours=True
        )

        assert overnight.value != next_morning.value


class TestEveryTierCanBeExplained:
    """A tier with no wording renders as a raw enum name on the one screen
    whose purpose is explaining what happened — the console equivalent of a
    raw translation key."""

    def test_every_source_has_a_sentence(self) -> None:
        from blinkengage.domain.resolution import SOURCE_TEXT, ConfigurationSource

        missing = [source for source in ConfigurationSource if source not in SOURCE_TEXT]

        assert not missing, f"tiers with no wording: {missing}"

    def test_and_none_of_them_reads_like_a_code(self) -> None:
        from blinkengage.domain.resolution import SOURCE_TEXT

        for source, text in SOURCE_TEXT.items():
            assert text and text[0].islower(), f"{source} reads like a heading, not a sentence"
            assert "_" not in text, f"{source} still contains an identifier"
