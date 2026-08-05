"""The Learning envelope and its feature extraction, in isolation.

Pure functions, so these are the cheap tests — and the ones that pin the
decisions most likely to be quietly "improved" later: that policy is
evaluated before content, that an all-AI conversation is not evidence,
and that extraction is deterministic enough for ``pipeline_version`` to
mean something.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from blinkengage.domain.learning_features import (
    detect_language,
    extract,
    extract_entities,
    extract_topics,
)
from blinkengage.domain.learning_observation import (
    MAX_CONTENT_REFS,
    MAX_TOPICS,
    ContentRef,
    ContentRefKind,
    ContentRefsRequiredError,
    ExclusionReason,
    Features,
    Observation,
    ObservationError,
    ObservationSource,
    ObservationState,
    Participants,
    Provenance,
    SourceKind,
    decide_state,
    validate,
)


def _observation(**overrides: object) -> Observation:
    defaults: dict[str, object] = {
        "company_id": uuid4(),
        "source": ObservationSource(
            kind=SourceKind.CONVERSATION,
            source_id=uuid4(),
            occurred_at=datetime.now(UTC),
        ),
        "participants": Participants(customer_id=uuid4()),
        "content_refs": (ContentRef(kind=ContentRefKind.MESSAGE, ref_id=uuid4()),),
        "provenance": Provenance(human_authored=2),
        "features": Features(human_char_count=100),
        "state": ObservationState.READY,
    }
    defaults.update(overrides)
    return Observation(**defaults)  # type: ignore[arg-type]


class TestProvenance:
    def test_an_empty_observation_is_not_fully_human(self) -> None:
        """0.0, not 1.0.

        The fraction feeds a *minimum* downstream. If "no content at all"
        answered 1.0 it would pass every floor ever set on it, which is
        the opposite of what a floor is for.
        """
        assert Provenance().human_authored_fraction == 0.0
        assert Provenance().is_evidence_bearing is False

    def test_ai_assisted_content_still_counts_as_seen(self) -> None:
        """Assisted is admitted; generated is not.

        A human read the draft and pressed send, so it is real content.
        What it may never do is *corroborate* — enforced by the Memory
        contract, not here.
        """
        provenance = Provenance(human_authored=1, ai_assisted=3)
        assert provenance.total == 4
        assert provenance.is_evidence_bearing is True
        assert provenance.human_authored_fraction == pytest.approx(0.25)

    def test_an_entirely_machine_written_exchange_bears_no_evidence(self) -> None:
        assert Provenance(ai_generated=9).is_evidence_bearing is False


class TestDecideState:
    def test_policy_is_evaluated_before_anything_else(self) -> None:
        """Order is the point.

        A company that forbade learning must get ``POLICY_DENIED`` — not
        ``NO_HUMAN_CONTENT`` — even when both are true. The reason is not
        cosmetic: the exclusion reason is the audit record of *why* the
        platform declined, and "we were not allowed to look" is a
        materially different answer to a regulator than "we looked and
        found nothing".
        """
        state, reason = decide_state(
            settled=True,
            provenance=Provenance(ai_generated=5),
            features=Features(human_char_count=0),
            policy_allows=False,
        )
        assert state is ObservationState.EXCLUDED
        assert reason is ExclusionReason.POLICY_DENIED

    def test_an_all_ai_conversation_is_excluded(self) -> None:
        state, reason = decide_state(
            settled=True,
            provenance=Provenance(ai_generated=5),
            features=Features(human_char_count=500),
            policy_allows=True,
        )
        assert state is ObservationState.EXCLUDED
        assert reason is ExclusionReason.NO_HUMAN_CONTENT

    def test_a_two_word_exchange_is_excluded(self) -> None:
        state, reason = decide_state(
            settled=True,
            provenance=Provenance(human_authored=2),
            features=Features(human_char_count=6),
            policy_allows=True,
        )
        assert state is ObservationState.EXCLUDED
        assert reason is ExclusionReason.TOO_SHORT

    @pytest.mark.parametrize(
        ("settled", "expected"),
        [(True, ObservationState.READY), (False, ObservationState.PENDING)],
    )
    def test_settlement_decides_ready_versus_pending(
        self, settled: bool, expected: ObservationState
    ) -> None:
        state, reason = decide_state(
            settled=settled,
            provenance=Provenance(human_authored=3),
            features=Features(human_char_count=400),
            policy_allows=True,
        )
        assert state is expected
        assert reason is None


class TestValidate:
    def test_an_observation_with_no_pointers_is_refused(self) -> None:
        """Traceability is a property of the store, not a habit.

        A row asserting that something happened, with nothing to check it
        against, is the same defect Memory refuses when a fact arrives
        with no evidence.
        """
        with pytest.raises(ContentRefsRequiredError):
            validate(_observation(content_refs=()))

    def test_an_excluded_observation_needs_no_pointers(self) -> None:
        """The exemption that makes exclusion recordable.

        "We saw this and chose not to learn" is worth keeping even when
        policy stopped the code before it read a single message — which
        is exactly when there is nothing to point at.
        """
        validate(
            _observation(
                content_refs=(),
                state=ObservationState.EXCLUDED,
                exclusion_reason=ExclusionReason.POLICY_DENIED,
            )
        )

    def test_an_excluded_observation_must_say_why(self) -> None:
        with pytest.raises(ObservationError, match="must say why"):
            validate(_observation(state=ObservationState.EXCLUDED, exclusion_reason=None))

    def test_the_envelope_is_bounded(self) -> None:
        refs = tuple(
            ContentRef(kind=ContentRefKind.MESSAGE, ref_id=uuid4(), ordinal=index)
            for index in range(MAX_CONTENT_REFS + 1)
        )
        with pytest.raises(ObservationError, match="more than the"):
            validate(_observation(content_refs=refs))


class TestLanguageDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("مرحبا، أريد استرجاع المبلغ", "ar"),
            ("Hello, I would like a refund", "en"),
            ("مرحبا، I need a refund على الطلب", "mixed"),
            ("12345 !!! ???", None),
            ("", None),
        ],
    )
    def test_script_based_detection(self, text: str, expected: str | None) -> None:
        assert detect_language(text) == expected

    def test_one_stray_latin_word_does_not_make_arabic_mixed(self) -> None:
        """``mixed`` means code-switching, not contamination.

        A product name or a URL fragment in an otherwise Arabic message is
        normal. If that flipped the language, most Arabic traffic on this
        platform would be labelled mixed and the feature would say
        nothing.
        """
        text = "مرحبا أريد استرجاع المبلغ للطلب رقم كذا وكذا شكرا لكم ok"
        assert detect_language(text) == "ar"


class TestEntityExtraction:
    def test_identifiers_are_extracted_by_shape_with_their_kind(self) -> None:
        entities = extract_entities(
            "Order ORD-4471 for a@b.com was refunded 25 JOD, see https://x.test/a"
        )
        assert "ref:ORD-4471" in entities
        assert "email:a@b.com" in entities
        assert "money:25 JOD" in entities
        assert "url:https://x.test/a" in entities

    def test_kinds_keep_colliding_values_distinct(self) -> None:
        """``ref:123456`` and a hypothetical other kind sharing ``123456``
        must not merge — which is the whole reason for the prefix."""
        entities = extract_entities("reference 123456 and 123456 again")
        assert entities.count("ref:123456") == 1

    def test_ordinary_prose_yields_nothing(self) -> None:
        assert extract_entities("the customer was unhappy about the delay") == ()


class TestTopicExtraction:
    def test_topics_are_frequency_ranked_and_stop_worded(self) -> None:
        topics = extract_topics(
            "The refund policy for the refund is unclear. Please explain the refund policy."
        )
        assert topics[0] == "refund"
        assert "policy" in topics
        assert "the" not in topics
        assert "please" not in topics

    def test_extraction_is_deterministic(self) -> None:
        """What makes ``pipeline_version`` a rollback boundary.

        If the same text produced different topics across runs, a version
        bump would be a label on a moving target and no two generations
        would be comparable.
        """
        text = "shipping delay refund shipping complaint delay refund escalation"
        assert extract_topics(text) == extract_topics(text)

    def test_ties_break_alphabetically(self) -> None:
        # Every token appears once, so only the tie-break decides order.
        assert extract_topics("zebra apple mango") == ("apple", "mango", "zebra")

    def test_topics_are_bounded(self) -> None:
        text = " ".join(f"token{index:03d}" for index in range(MAX_TOPICS * 3))
        assert len(extract_topics(text)) == MAX_TOPICS

    def test_arabic_tokenises_like_anything_else(self) -> None:
        topics = extract_topics("استرجاع المبلغ استرجاع الطلب شكرا")
        assert "استرجاع" in topics
        assert "شكرا" not in topics


class TestExtract:
    def test_it_assembles_tier_zero_and_tier_one(self) -> None:
        features = extract(
            human_text="I want a refund for order ORD-4471, the refund never arrived",
            inbound_turns=3,
            outbound_turns=2,
        )
        assert features.language == "en"
        assert features.topics[0] == "refund"
        assert "ref:ORD-4471" in features.entities
        assert features.inbound_turns == 3
        assert features.outbound_turns == 2
        assert features.human_char_count > 0

    def test_the_char_count_ignores_surrounding_whitespace(self) -> None:
        """It gates the too-short exclusion, so it must measure content.

        A conversation of four blank turns would otherwise clear a
        character floor on its newlines alone.
        """
        assert (
            extract(human_text="\n\n  \n", inbound_turns=4, outbound_turns=0).human_char_count == 0
        )
