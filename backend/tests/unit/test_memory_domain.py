"""The pure memory rules: contract, confidence, lifecycle, identity.

No database. These are the rules the whole platform rests on, and they are
testable in isolation precisely because they were kept free of I/O.
"""

from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.memory import (
    ConfidenceDirection,
    ConfidenceState,
    EvidenceRef,
    EvidenceRequiredError,
    EvidenceSourceType,
    HumanState,
    LifecycleState,
    MemoryTier,
    SubjectRef,
    SubjectTierMismatchError,
    SubjectType,
    UnknownFactTypeError,
    validate_fact_shape,
)
from blinkengage.domain.memory_confidence import (
    ConfidenceInputs,
    DirectionInputs,
    compute_confidence,
    compute_direction,
    next_confidence_state,
    recency_factor,
)
from blinkengage.domain.memory_identity import fact_key, normalise_key, stratum_key
from blinkengage.domain.memory_lifecycle import (
    LifecycleInputs,
    RetentionPolicy,
    display_label,
    is_retrievable,
    next_lifecycle_state,
    revive_on_observation,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _evidence(**kwargs: object) -> EvidenceRef:
    return EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, **kwargs)  # type: ignore[arg-type]


class TestTheFactContract:
    def test_a_fact_without_evidence_is_refused(self) -> None:
        """Not a validation nicety. A fact with no evidence cannot be
        explained, re-derived, or correctly weakened when an erasure
        removes what supported it — so it is an assertion, and this
        platform does not store assertions."""
        with pytest.raises(EvidenceRequiredError):
            validate_fact_shape(
                tier=MemoryTier.ORGANIZATIONAL,
                fact_type="terminology",
                subject=SubjectRef(SubjectType.COMPANY, _uuid()),
                evidence=(),
            )

    def test_an_unknown_fact_type_is_refused(self) -> None:
        with pytest.raises(UnknownFactTypeError):
            validate_fact_shape(
                tier=MemoryTier.ORGANIZATIONAL,
                fact_type="not_a_real_type",
                subject=SubjectRef(SubjectType.COMPANY, _uuid()),
                evidence=(_evidence(),),
            )

    def test_organizational_memory_cannot_be_about_a_customer(self) -> None:
        """The most damaging mistake available in this schema: a customer
        fact wearing the tier that survives erasure."""
        with pytest.raises(SubjectTierMismatchError):
            validate_fact_shape(
                tier=MemoryTier.ORGANIZATIONAL,
                fact_type="terminology",
                subject=SubjectRef(SubjectType.CUSTOMER, _uuid()),
                evidence=(_evidence(),),
            )

    def test_experience_may_be_about_the_company_or_an_agent(self) -> None:
        for subject_type in (SubjectType.COMPANY, SubjectType.AGENT):
            validate_fact_shape(
                tier=MemoryTier.EXPERIENCE,
                fact_type="effective_response",
                subject=SubjectRef(subject_type, _uuid()),
                evidence=(_evidence(),),
            )


class TestConfidence:
    def test_breadth_beats_volume(self) -> None:
        """Forty repetitions by one agent is one habit; six agents
        converging independently is a practice. A formula that cannot tell
        them apart promotes the first into company policy."""
        one_person = compute_confidence(
            ConfidenceInputs(
                support_count=40,
                distinct_customer_count=1,
                distinct_agent_count=1,
                contradiction_count=0,
                last_observed_at=NOW,
                now=NOW,
                fact_type="objection",
                has_corroboration=True,
            )
        )
        many_people = compute_confidence(
            ConfidenceInputs(
                support_count=12,
                distinct_customer_count=10,
                distinct_agent_count=6,
                contradiction_count=0,
                last_observed_at=NOW,
                now=NOW,
                fact_type="objection",
                has_corroboration=True,
            )
        )

        assert many_people > one_person

    def test_contradictions_reduce_confidence(self) -> None:
        base = ConfidenceInputs(
            support_count=10,
            distinct_customer_count=5,
            distinct_agent_count=3,
            contradiction_count=0,
            last_observed_at=NOW,
            now=NOW,
            fact_type="objection",
            has_corroboration=True,
        )
        contradicted = ConfidenceInputs(**{**base.__dict__, "contradiction_count": 4})

        assert compute_confidence(contradicted) < compute_confidence(base)

    def test_confidence_decays_with_age(self) -> None:
        fresh = ConfidenceInputs(
            support_count=10,
            distinct_customer_count=5,
            distinct_agent_count=3,
            contradiction_count=0,
            last_observed_at=NOW,
            now=NOW,
            fact_type="recurring_issue",
            has_corroboration=True,
        )
        stale = ConfidenceInputs(
            **{**fresh.__dict__, "last_observed_at": NOW - timedelta(days=365)}
        )

        assert compute_confidence(stale) < compute_confidence(fresh)

    def test_terminology_decays_far_slower_than_a_promise(self) -> None:
        """A single global half-life would either expire stable facts or
        preserve stale ones, and both failures are silent."""
        age = timedelta(days=120)
        term = recency_factor(last_observed_at=NOW - age, now=NOW, fact_type="terminology")
        promise = recency_factor(last_observed_at=NOW - age, now=NOW, fact_type="promise_made")

        assert term > 0.9
        assert promise < 0.1

    def test_a_future_observation_does_not_amplify(self) -> None:
        """Clock skew or a bad import timestamp must not manufacture
        confidence."""
        assert (
            recency_factor(
                last_observed_at=NOW + timedelta(days=30), now=NOW, fact_type="objection"
            )
            == 1.0
        )

    def test_repetition_alone_cannot_reach_confirmed(self) -> None:
        """The structural defence against belief-by-repetition. A customer
        asserting the same thing a hundred times is one person's assertion
        observed a hundred times."""
        state = next_confidence_state(
            current=ConfidenceState.CANDIDATE,
            confidence=0.99,
            has_corroboration=False,
        )

        assert state is ConfidenceState.CANDIDATE

    def test_corroboration_unlocks_the_higher_states(self) -> None:
        state = next_confidence_state(
            current=ConfidenceState.CANDIDATE, confidence=0.99, has_corroboration=True
        )

        assert state is ConfidenceState.TRUSTED

    def test_hysteresis_prevents_flapping(self) -> None:
        """Promotion and demotion thresholds differ, so a fact hovering on
        a boundary does not change state on every nightly recompute — and
        each change is something downstream reacts to."""
        just_below = next_confidence_state(
            current=ConfidenceState.TRUSTED, confidence=0.78, has_corroboration=True
        )

        assert just_below is ConfidenceState.TRUSTED

        clearly_below = next_confidence_state(
            current=ConfidenceState.TRUSTED, confidence=0.60, has_corroboration=True
        )
        assert clearly_below is ConfidenceState.CONFIRMED


class TestDirection:
    def test_growing_support_is_rising(self) -> None:
        assert (
            compute_direction(DirectionInputs(supporting_delta=3, contradicting_delta=0, samples=4))
            is ConfidenceDirection.RISING
        )

    def test_growing_contradiction_is_falling(self) -> None:
        assert (
            compute_direction(DirectionInputs(supporting_delta=0, contradicting_delta=2, samples=4))
            is ConfidenceDirection.FALLING
        )

    def test_both_growing_is_contested(self) -> None:
        """A distinct and more actionable finding than either direction:
        the company is being inconsistent about something. Two departments
        quoting different lead times produce exactly this."""
        assert (
            compute_direction(DirectionInputs(supporting_delta=3, contradicting_delta=3, samples=5))
            is ConfidenceDirection.CONTESTED
        )

    def test_a_quiet_fact_is_stable_not_falling(self) -> None:
        """The correction that decides whether this feature works at all.
        Confidence includes decay, so differencing it would report FALLING
        for every fact that is merely quiet — which is most facts."""
        assert (
            compute_direction(DirectionInputs(supporting_delta=0, contradicting_delta=0, samples=6))
            is ConfidenceDirection.STABLE
        )

    def test_one_sample_is_not_a_trend(self) -> None:
        assert (
            compute_direction(DirectionInputs(supporting_delta=5, contradicting_delta=0, samples=1))
            is ConfidenceDirection.UNKNOWN
        )


class TestLifecycle:
    POLICY = RetentionPolicy()

    def _inputs(self, **kwargs: object) -> LifecycleInputs:
        base = {
            "current": LifecycleState.ACTIVE,
            "last_observed_at": NOW,
            "now": NOW,
            "human_state": HumanState.UNREVIEWED,
            "policy": self.POLICY,
        }
        base.update(kwargs)
        return LifecycleInputs(**base)  # type: ignore[arg-type]

    def test_a_fresh_fact_is_active(self) -> None:
        assert next_lifecycle_state(self._inputs()) is LifecycleState.ACTIVE

    def test_age_moves_it_through_the_states(self) -> None:
        for days, expected in [
            (200, LifecycleState.DORMANT),
            (600, LifecycleState.ARCHIVED),
            (1200, LifecycleState.PURGED),
        ]:
            state = next_lifecycle_state(self._inputs(last_observed_at=NOW - timedelta(days=days)))
            assert state is expected, f"{days} days should be {expected}"

    def test_re_observation_revives_a_dormant_fact_without_touching_belief(self) -> None:
        """The case a single chain cannot express. Walking confidence back
        down would make the fact *less* believed on strictly *more*
        evidence."""
        assert revive_on_observation(LifecycleState.DORMANT) is LifecycleState.ACTIVE

    def test_an_archived_fact_does_not_revive_automatically(self) -> None:
        """Its evidence has been pruned, so a revived row would carry
        counters it can no longer justify."""
        assert revive_on_observation(LifecycleState.ARCHIVED) is LifecycleState.ARCHIVED

    def test_suppression_outranks_the_schedule(self) -> None:
        """Somebody muted this deliberately. Ageing it out would remove it
        for a reason unrelated to why it was muted — and purging it would
        simply let it be re-learned next week."""
        state = next_lifecycle_state(
            self._inputs(
                current=LifecycleState.ACTIVE,
                last_observed_at=NOW - timedelta(days=2000),
                human_state=HumanState.SUPPRESSED,
            )
        )

        assert state is LifecycleState.ACTIVE

    def test_losing_all_evidence_archives_rather_than_purges(self) -> None:
        """What happens to an aggregate fact after an erasure removes the
        last of its support. The row is the record that the platform once
        believed this; an erasure request did not ask for the company's own
        history to be rewritten."""
        state = next_lifecycle_state(self._inputs(has_evidence=False))

        assert state is LifecycleState.ARCHIVED

    def test_an_explicit_expiry_outranks_the_default_schedule(self) -> None:
        state = next_lifecycle_state(self._inputs(expires_at=NOW - timedelta(days=1)))

        assert state is LifecycleState.ARCHIVED

    def test_retention_must_increase(self) -> None:
        with pytest.raises(ValueError, match="must increase strictly"):
            RetentionPolicy(dormant_after_days=100, archive_after_days=50, purge_after_days=200)


class TestRetrievability:
    def test_suppressed_facts_are_never_retrievable(self) -> None:
        assert not is_retrievable(
            lifecycle=LifecycleState.ACTIVE, human_state=HumanState.SUPPRESSED
        )

    def test_dormant_facts_are_still_retrievable(self) -> None:
        """Dormant means quiet, not wrong. A fact nobody has re-observed
        this quarter is still the best answer available."""
        assert is_retrievable(lifecycle=LifecycleState.DORMANT, human_state=HumanState.UNREVIEWED)

    def test_archived_facts_are_not_retrievable(self) -> None:
        assert not is_retrievable(
            lifecycle=LifecycleState.ARCHIVED, human_state=HumanState.UNREVIEWED
        )


class TestDisplayLabels:
    def test_the_two_axes_collapse_into_one_word(self) -> None:
        """The product vocabulary stays one-dimensional; the storage does
        not. Deriving the label in one place keeps both."""
        assert (
            display_label(
                confidence_state="trusted",
                lifecycle=LifecycleState.DORMANT,
                human_state=HumanState.UNREVIEWED,
                contradicted=False,
            )
            == "stale"
        )
        assert (
            display_label(
                confidence_state="trusted",
                lifecycle=LifecycleState.ACTIVE,
                human_state=HumanState.UNREVIEWED,
                contradicted=False,
            )
            == "trusted"
        )
        assert (
            display_label(
                confidence_state="trusted",
                lifecycle=LifecycleState.ACTIVE,
                human_state=HumanState.SUPPRESSED,
                contradicted=False,
            )
            == "suppressed"
        )
        assert (
            display_label(
                confidence_state="trusted",
                lifecycle=LifecycleState.ACTIVE,
                human_state=HumanState.UNREVIEWED,
                contradicted=True,
            )
            == "contradicted"
        )


class TestIdentity:
    def test_casing_and_spacing_do_not_fork_a_fact(self) -> None:
        assert normalise_key("Prefers  Arabic ") == normalise_key("prefers arabic")

    def test_arabic_orthographic_variants_fold_together(self) -> None:
        """Which alef somebody typed is a keyboard artefact, not a
        different fact."""
        assert normalise_key("أحمد") == normalise_key("احمد")

    def test_arabic_diacritics_are_ignored(self) -> None:
        assert normalise_key("مَرْحَبا") == normalise_key("مرحبا")

    def test_an_empty_key_is_stable_rather_than_colliding_on_blank(self) -> None:
        assert normalise_key("   ") == normalise_key("!!!")

    def test_a_very_long_key_is_hashed_not_truncated(self) -> None:
        """Truncation makes two long distinct keys collide on their shared
        prefix — and long keys are exactly the descriptive ones most likely
        to share one."""
        first = normalise_key("refund policy " * 40 + "alpha")
        second = normalise_key("refund policy " * 40 + "beta")

        assert first != second

    def test_stratum_order_does_not_change_identity(self) -> None:
        assert stratum_key({"tier": "vip", "channel": "whatsapp"}) == stratum_key(
            {"channel": "whatsapp", "tier": "vip"}
        )

    def test_the_same_claim_in_two_strata_is_two_facts(self) -> None:
        """Experience facts are compared within a stratum, never pooled —
        pooling is how an approach that wins in every segment loses
        overall."""
        vip = fact_key(topic="fast refund", stratum={"tier": "vip"})
        standard = fact_key(topic="fast refund", stratum={"tier": "standard"})

        assert vip != standard


def _uuid():
    from uuid import uuid4

    return uuid4()
