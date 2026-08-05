"""The Learning envelope and its feature extraction, in isolation.

Pure functions, so these are the cheap tests — and the ones that pin the
decisions most likely to be quietly "improved" later: that policy is
evaluated before content, that an all-AI conversation is not evidence,
and that extraction is deterministic enough for ``pipeline_version`` to
mean something.
"""

from datetime import UTC, datetime, timedelta
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
        # Word-shaped, not identifier-shaped: a token mixing letters and
        # digits is dropped as an identifier fragment, which is the point
        # of the rule and would make this measure nothing.
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        text = " ".join(
            f"{alphabet[index % 26]}{alphabet[(index // 26) % 26]}word"
            for index in range(MAX_TOPICS * 3)
        )
        assert len(extract_topics(text)) == MAX_TOPICS

    def test_arabic_tokenises_like_anything_else(self) -> None:
        topics = extract_topics("استرجاع المبلغ استرجاع الطلب شكرا")
        assert "استرجاع" in topics
        assert "شكرا" not in topics


class TestProductionFoundDefects:
    """Regressions for what phase 1.5 validation found in real traffic.

    Both were invisible to the labelled corpus, because the corpus was
    written by the same hand as the extractor. That is the argument for
    validating against production data rather than against a benchmark.
    """

    def test_a_url_contributes_nothing_to_topics(self) -> None:
        """The defect, exactly as it appeared.

        A CSAT survey link put UUID segments and JWT fragments through the
        tokeniser, and they became topics. At clustering, a token present
        in every conversation that happened to receive a survey link is a
        pattern that is not there.
        """
        body = (
            "please take a moment to share your feedback: "
            "https://10.0.0.1/feedback/e8aa3a07-e1b9-4350-9d1d-bc0a287c1184"
            "?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc"
        )
        topics = extract_topics(body)
        for fragment in ("e8aa3a07", "e1b9", "9d1d", "bc0a287c1184", "eyjhbgcioijiuzi1nij9"):
            assert fragment not in topics
        # The URL itself is still kept — as an entity, where it belongs.
        assert any(entity.startswith("url:") for entity in extract_entities(body))

    def test_a_word_that_happens_to_be_hexadecimal_survives(self) -> None:
        """Why the rule is "letters and digits", not "looks like hex".

        ``cafe``, ``dead``, ``decade`` and ``face`` are all valid
        hexadecimal and all ordinary English. A hex test would silently
        delete them from every topic list on the platform.
        """
        topics = extract_topics("the cafe order was dead on arrival, a decade of decay")
        assert "cafe" in topics
        assert "dead" in topics
        assert "decade" in topics

    def test_identifier_fragments_are_dropped_but_words_are_not(self) -> None:
        assert extract_topics("gl9pwqnk refund a1b2c3 shipping") == ("refund", "shipping")


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


class TestSettleRunWindows:
    """The run row is a window, and the window must match the cadence.

    Phase 2 moved this helper into ``learning_run_window`` because three
    sweeps now share it — and duplicating the rule per sweep is exactly
    how the defect below comes back.

    Found in phase 1.5: the sweep truncated its window to the hour while
    running every fifteen minutes, so three runs in four collided on the
    unique constraint and recorded nothing — including their failures,
    which is what made it worth finding. An operator watching ``failed``
    would have seen zero through a sweep that was failing every time.
    """

    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            ("13:00:45", "13:00:00"),
            ("13:13:10", "13:00:00"),
            ("13:14:59", "13:00:00"),
            ("13:15:00", "13:15:00"),
            ("13:29:59", "13:15:00"),
        ],
    )
    def test_consecutive_sweeps_get_their_own_window(self, moment: str, expected: str) -> None:
        from blinkengage.infrastructure.tasks.learning_run_window import window_start

        _window_start = window_start
        hour, minute, second = (int(part) for part in moment.split(":"))
        floored = _window_start(datetime(2026, 8, 5, hour, minute, second, tzinfo=UTC), seconds=900)
        assert floored.strftime("%H:%M:%S") == expected

    def test_a_cadence_that_does_not_divide_an_hour_still_tiles(self) -> None:
        """Epoch-anchored, not hour-anchored.

        A 7-minute cadence anchored to the hour would leave a short,
        overlapping window at the top of every hour — and an overlap is a
        collision, which is a run that records nothing.
        """
        from blinkengage.infrastructure.tasks.learning_run_window import window_start

        _window_start = window_start
        step = 7 * 60
        base = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)
        windows = sorted(
            {
                _window_start(base + timedelta(seconds=offset), seconds=step)
                for offset in range(0, step * 6, 30)
            }
        )

        # Contiguous and exactly one step apart: no gap where a run would
        # be unrecorded, no overlap where two would collide.
        assert len(windows) >= 6
        gaps = {
            (later - earlier).total_seconds()
            for earlier, later in zip(windows, windows[1:], strict=False)
        }
        assert gaps == {float(step)}
