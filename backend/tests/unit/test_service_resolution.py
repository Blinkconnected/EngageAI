"""How a conversation's Service is decided, and why the losing stages matter.

The pipeline's value is not that it produces an answer — one function could do
that. It is that it produces an answer **with its reasoning intact**, including
from the stages that declined. Almost every test here is about a stage that did
*not* resolve, because that is the information a single-decision model throws
away and an administrator needs.
"""

import uuid
from decimal import Decimal

import pytest

from blinkengage.domain.service_resolution import (
    DEFAULT_STAGE_ORDER,
    ResolutionRequest,
    ResolutionStrategy,
    StageOutcome,
    StageReason,
    StageResult,
    resolve_service,
)

BILLING = uuid.uuid4()
SUPPORT = uuid.uuid4()


class Stage:
    """A stage that returns whatever the test told it to."""

    def __init__(self, strategy: ResolutionStrategy, result: StageResult | Exception) -> None:
        self._strategy = strategy
        self._result = result
        self.was_asked = False

    @property
    def strategy(self) -> ResolutionStrategy:
        return self._strategy

    async def resolve(self, request: ResolutionRequest) -> StageResult:
        self.was_asked = True
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def resolved(strategy: ResolutionStrategy, service_id: uuid.UUID, **kw) -> StageResult:
    return StageResult(
        strategy=strategy,
        outcome=StageOutcome.RESOLVED,
        reason=kw.pop("reason", StageReason.RULE_MATCHED),
        service_id=service_id,
        **kw,
    )


def declined(strategy: ResolutionStrategy, outcome: StageOutcome, reason: StageReason, **kw):
    return StageResult(strategy=strategy, outcome=outcome, reason=reason, **kw)


def a_request() -> ResolutionRequest:
    return ResolutionRequest(
        company_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        channel_type="whatsapp",
        body="I was charged twice",
        customer_id=uuid.uuid4(),
    )


class TestThePipelineStopsAtTheFirstAnswer:
    async def test_it_resolves_and_asks_nothing_further(self) -> None:
        first = Stage(
            ResolutionStrategy.CUSTOMER_SELECTION,
            resolved(ResolutionStrategy.CUSTOMER_SELECTION, BILLING),
        )
        later = Stage(
            ResolutionStrategy.AI_CLASSIFICATION,
            resolved(ResolutionStrategy.AI_CLASSIFICATION, SUPPORT),
        )

        result = await resolve_service((first, later), a_request())

        assert result.service_id == BILLING
        assert result.resolved
        # A stage after the answer must not run: a classifier that costs a
        # provider call has no business being asked once the customer has
        # already said what they want.
        assert later.was_asked is False

    async def test_every_stage_that_ran_is_kept_not_only_the_winner(self) -> None:
        """The whole point. A single-decision model would keep the last line
        of this and discard the two above it, which are the two an
        administrator actually asks about."""
        stages = (
            Stage(
                ResolutionStrategy.VIP_RULE,
                declined(
                    ResolutionStrategy.VIP_RULE,
                    StageOutcome.SKIPPED,
                    StageReason.NOT_CONFIGURED,
                ),
            ),
            Stage(
                ResolutionStrategy.AI_CLASSIFICATION,
                declined(
                    ResolutionStrategy.AI_CLASSIFICATION,
                    StageOutcome.CONTINUE,
                    StageReason.BELOW_CONFIDENCE_THRESHOLD,
                    confidence=Decimal("0.68"),
                ),
            ),
            Stage(
                ResolutionStrategy.BUSINESS_RULES,
                resolved(ResolutionStrategy.BUSINESS_RULES, BILLING),
            ),
        )

        result = await resolve_service(stages, a_request())

        assert [stage.strategy for stage in result.stages] == [
            ResolutionStrategy.VIP_RULE,
            ResolutionStrategy.AI_CLASSIFICATION,
            ResolutionStrategy.BUSINESS_RULES,
        ]
        assert result.stages[1].confidence == Decimal("0.68")
        assert result.deciding_stage is not None
        assert result.deciding_stage.strategy is ResolutionStrategy.BUSINESS_RULES


class TestTheFourOutcomesAreDistinct:
    async def test_skipped_and_continue_are_not_the_same_fact(self) -> None:
        """ "AI was not confident" and "AI is switched off" look identical on
        a screen that conflates them, and only one is a configuration
        problem."""
        off = declined(
            ResolutionStrategy.AI_CLASSIFICATION,
            StageOutcome.SKIPPED,
            StageReason.NOT_CONFIGURED,
        )
        unsure = declined(
            ResolutionStrategy.AI_CLASSIFICATION,
            StageOutcome.CONTINUE,
            StageReason.BELOW_CONFIDENCE_THRESHOLD,
            confidence=Decimal("0.40"),
        )

        assert off.outcome is not unsure.outcome
        assert "not configured" in off.sentence
        assert "not confident enough" in unsure.sentence

    async def test_a_rejection_stops_the_pipeline_dead(self) -> None:
        """Distinct from resolving to nothing: the stages after a refusal do
        not get a turn, because the refusal is the answer."""
        refuse = Stage(
            ResolutionStrategy.VIP_RULE,
            declined(
                ResolutionStrategy.VIP_RULE,
                StageOutcome.REJECTED,
                StageReason.REFUSED_BY_RULE,
            ),
        )
        fallback = Stage(
            ResolutionStrategy.FIXED_SERVICE,
            resolved(ResolutionStrategy.FIXED_SERVICE, SUPPORT),
        )

        result = await resolve_service((refuse, fallback), a_request())

        assert result.resolved is False
        assert result.rejected is True
        assert fallback.was_asked is False

    async def test_every_stage_declining_is_an_answer_not_an_error(self) -> None:
        stages = (
            Stage(
                ResolutionStrategy.BUSINESS_RULES,
                declined(
                    ResolutionStrategy.BUSINESS_RULES,
                    StageOutcome.CONTINUE,
                    StageReason.NO_MATCH,
                ),
            ),
        )

        result = await resolve_service(stages, a_request())

        assert result.service_id is None
        assert result.resolved is False
        assert result.rejected is False
        assert len(result.stages) == 1


class TestABrokenStageNeverSwallowsAMessage:
    async def test_a_raising_stage_is_recorded_and_the_pipeline_continues(self) -> None:
        """An exception inside a classifier must not be the reason a
        customer's message goes nowhere."""
        broken = Stage(ResolutionStrategy.EXTERNAL_API, RuntimeError("CRM timed out"))
        after = Stage(
            ResolutionStrategy.FIXED_SERVICE,
            resolved(ResolutionStrategy.FIXED_SERVICE, SUPPORT, reason=StageReason.FALLBACK),
        )

        result = await resolve_service((broken, after), a_request())

        assert result.service_id == SUPPORT
        failed = result.stages[0]
        assert failed.outcome is StageOutcome.SKIPPED
        assert failed.reason is StageReason.STRATEGY_FAILED
        # The error is kept, so "why did the CRM stage not run" is answerable.
        assert "CRM timed out" in str(failed.evidence["error"])

    async def test_a_failure_is_skipped_rather_than_rejected(self) -> None:
        """Rejection is a deliberate refusal. A crash is not a decision, and
        recording it as one would stop every stage after it."""
        broken = Stage(ResolutionStrategy.CHATBOT_FLOW, ValueError("boom"))
        after = Stage(
            ResolutionStrategy.BUSINESS_RULES,
            resolved(ResolutionStrategy.BUSINESS_RULES, BILLING),
        )

        result = await resolve_service((broken, after), a_request())

        assert after.was_asked is True
        assert result.service_id == BILLING


class TestAStageCannotContradictItself:
    def test_resolving_without_a_service_is_refused(self) -> None:
        with pytest.raises(ValueError, match="resolved without naming a service"):
            StageResult(
                strategy=ResolutionStrategy.BUSINESS_RULES,
                outcome=StageOutcome.RESOLVED,
                reason=StageReason.RULE_MATCHED,
            )

    def test_naming_a_service_while_declining_is_refused(self) -> None:
        """Otherwise a conversation goes somewhere no stage claimed to
        choose, and the log would say it was never resolved."""
        with pytest.raises(ValueError, match="must say it resolved"):
            StageResult(
                strategy=ResolutionStrategy.AI_CLASSIFICATION,
                outcome=StageOutcome.CONTINUE,
                reason=StageReason.BELOW_CONFIDENCE_THRESHOLD,
                service_id=BILLING,
            )


class TestTheDefaultOrder:
    def test_an_override_runs_before_a_classifier(self) -> None:
        """An override that runs after a classifier is not an override."""
        order = list(DEFAULT_STAGE_ORDER)

        assert order.index(ResolutionStrategy.VIP_RULE) < order.index(
            ResolutionStrategy.AI_CLASSIFICATION
        )
        assert order.index(ResolutionStrategy.EXTERNAL_API) < order.index(
            ResolutionStrategy.AI_CLASSIFICATION
        )

    def test_the_customer_is_asked_before_a_classifier_guesses(self) -> None:
        """They know what they want better than a classifier does."""
        order = list(DEFAULT_STAGE_ORDER)

        assert order.index(ResolutionStrategy.CUSTOMER_SELECTION) < order.index(
            ResolutionStrategy.AI_CLASSIFICATION
        )

    def test_the_fallback_is_last(self) -> None:
        """A fallback that runs before anything else is not a fallback."""
        assert DEFAULT_STAGE_ORDER[-1] is ResolutionStrategy.FIXED_SERVICE

    def test_every_strategy_appears_exactly_once(self) -> None:
        assert sorted(DEFAULT_STAGE_ORDER) == sorted(set(DEFAULT_STAGE_ORDER))
        assert set(DEFAULT_STAGE_ORDER) == set(ResolutionStrategy)


class TestEvidenceCarriesNoCustomerText:
    async def test_the_request_body_is_not_copied_into_a_stage_result(self) -> None:
        """A routing decision does not need the customer's message, and an
        append-only log is the wrong place to copy one into."""
        request = a_request()
        stage = Stage(
            ResolutionStrategy.AI_CLASSIFICATION,
            declined(
                ResolutionStrategy.AI_CLASSIFICATION,
                StageOutcome.CONTINUE,
                StageReason.BELOW_CONFIDENCE_THRESHOLD,
                confidence=Decimal("0.51"),
                evidence={"considered": ["billing", "support"]},
            ),
        )

        result = await resolve_service((stage,), request)

        assert request.body is not None
        assert request.body not in str(result.stages[0].evidence)
