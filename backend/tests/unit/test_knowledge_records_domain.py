"""The rules structured knowledge holds regardless of caller.

Pure-domain tests: no session, no app, no clock beyond what is passed in.
The canonical key gets the most attention because it is the one function
whose output is stored and later matched against — a key that changed
between releases would fork every product's history in two, and nothing
would raise.
"""

from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.knowledge_records import (
    SENSITIVE_RECORD_TYPES,
    AttributeSchemaError,
    EffectivePeriodError,
    InvalidLifecycleTransitionError,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    ProvenanceRequiredError,
    SubjectKeyNotDerivableError,
    SubjectLabelRequiredError,
    canonical_subject_key,
    normalise_subject_label,
    validate_attributes,
    validate_effective_period,
    validate_publishable,
    validate_transition,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)


class TestCanonicalSubjectKey:
    @pytest.mark.parametrize(
        "label",
        [
            "DIA 500 Mbps",
            "  DIA 500 Mbps  ",
            "dia 500 mbps",
            "DIA/500 Mbps",
            "DIA_500_Mbps",
            "DIA  —  500   Mbps",
            "DIA.500.Mbps",
        ],
    )
    def test_spelling_variants_are_one_subject(self, label: str) -> None:
        # The whole point: a price list written by three people on three
        # days is one product, not three.
        assert canonical_subject_key(label) == "dia-500-mbps"

    def test_is_idempotent(self) -> None:
        # Guards a specific accident: code that canonicalises an
        # already-canonical key. If that were lossy, a round trip through
        # the API would silently rename a subject.
        once = canonical_subject_key("DIA 500 Mbps")
        assert canonical_subject_key(once) == once

    def test_is_deterministic_across_calls(self) -> None:
        assert canonical_subject_key("DIA 500") == canonical_subject_key("DIA 500")

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            # Teh marbuta vs heh — both spellings occur constantly.
            ("الخدمة", "الخدمه"),
            # Diacritics are presentational.
            ("الخِدْمَة", "الخدمه"),
            # Tatweel is a typographic stretch, not a letter.
            ("خدمـــه", "خدمه"),
            # Alef with hamza/madda/wasla all fold to bare alef.
            ("إيه", "ايه"),
            ("أيه", "ايه"),
            ("آيه", "ايه"),
            # Alef maksura vs yeh.
            ("مبنى", "مبني"),
        ],
    )
    def test_arabic_orthographic_variants_agree(self, left: str, right: str) -> None:
        assert canonical_subject_key(left) == canonical_subject_key(right)

    def test_arabic_indic_digits_fold_to_ascii(self) -> None:
        # NFKC does *not* do this — verified in the implementation's
        # docstring. Without the explicit fold, a price typed on an Arabic
        # keyboard is a different product from the same price typed on a
        # Latin one.
        assert canonical_subject_key("خدمة ٥٠٠") == canonical_subject_key("خدمة 500")

    def test_persian_digits_fold_too(self) -> None:
        assert canonical_subject_key("خدمة ۵۰۰") == canonical_subject_key("خدمة 500")

    def test_mixed_script_survives(self) -> None:
        assert canonical_subject_key("DIA ٥٠٠ ميغا") == "dia-500-ميغا"

    def test_distinct_products_stay_distinct(self) -> None:
        # The failure that would matter: over-folding until two real
        # products collide.
        assert canonical_subject_key("DIA 500 Mbps") != canonical_subject_key("DIA 200 Mbps")

    def test_case_folding_handles_non_ascii(self) -> None:
        # ``casefold``, not ``lower`` — German sharp s is the classic case
        # where the two differ.
        assert canonical_subject_key("STRASSE") == canonical_subject_key("straße")

    def test_key_is_bounded(self) -> None:
        key = canonical_subject_key("word " * 200)
        assert len(key) <= 200
        assert not key.endswith("-")

    def test_blank_label_is_refused(self) -> None:
        with pytest.raises(SubjectLabelRequiredError):
            canonical_subject_key("   ")

    def test_label_with_no_letters_or_digits_is_refused(self) -> None:
        # Rather than inventing a hash-based key nobody can look up and
        # nobody chose.
        with pytest.raises(SubjectKeyNotDerivableError):
            canonical_subject_key("---///---")


class TestSubjectLabel:
    def test_preserves_authored_capitalisation(self) -> None:
        # The key is for lookup; the label is what a human reads.
        assert normalise_subject_label("  DIA   500   Mbps ") == "DIA 500 Mbps"


class TestAttributes:
    def test_price_requires_amount_and_currency(self) -> None:
        with pytest.raises(AttributeSchemaError):
            validate_attributes(KnowledgeRecordType.PRICE, {"currency": "JOD"})

    def test_unknown_attributes_are_rejected_not_stored(self) -> None:
        # A price carrying a stray ``discount`` nobody validated is a
        # number that will eventually be read as authoritative.
        with pytest.raises(AttributeSchemaError, match="discount"):
            validate_attributes(
                KnowledgeRecordType.PRICE,
                {"amount": "180", "currency": "JOD", "discount": "10"},
            )

    def test_amount_is_stored_as_a_string_never_a_float(self) -> None:
        # A float round trip turns 0.1 into 0.1000000000000000055 and a
        # quoted amount into an argument.
        cleaned = validate_attributes(
            KnowledgeRecordType.PRICE, {"amount": "180.50", "currency": "JOD"}
        )
        assert cleaned["amount"] == "180.50"
        assert isinstance(cleaned["amount"], str)

    def test_negative_price_is_refused(self) -> None:
        with pytest.raises(AttributeSchemaError):
            validate_attributes(KnowledgeRecordType.PRICE, {"amount": "-1", "currency": "JOD"})

    def test_non_numeric_amount_is_refused(self) -> None:
        with pytest.raises(AttributeSchemaError):
            validate_attributes(KnowledgeRecordType.PRICE, {"amount": "cheap", "currency": "JOD"})

    def test_currency_must_be_iso_4217_shaped(self) -> None:
        with pytest.raises(AttributeSchemaError, match="ISO-4217"):
            validate_attributes(
                KnowledgeRecordType.PRICE, {"amount": "180", "currency": "Jordanian"}
            )

    def test_currency_is_upper_cased(self) -> None:
        cleaned = validate_attributes(
            KnowledgeRecordType.PRICE, {"amount": "180", "currency": "jod"}
        )
        assert cleaned["currency"] == "JOD"

    def test_validator_does_not_mutate_its_input(self) -> None:
        # A validator that edits its input makes "what did the user send"
        # unanswerable two frames later.
        payload = {"amount": "180", "currency": "jod"}
        validate_attributes(KnowledgeRecordType.PRICE, payload)
        assert payload == {"amount": "180", "currency": "jod"}


class TestEffectivePeriod:
    def test_until_must_follow_from(self) -> None:
        with pytest.raises(EffectivePeriodError):
            validate_effective_period(NOW, NOW - timedelta(days=1))

    def test_naive_datetimes_are_refused(self) -> None:
        # A price effective at "2026-08-01 00:00" in an unknown zone is a
        # price effective on two different days depending on the reader.
        with pytest.raises(EffectivePeriodError):
            validate_effective_period(datetime(2026, 8, 1), None)

    def test_open_ended_period_covers_the_far_future(self) -> None:
        period = validate_effective_period(NOW, None)
        assert period.covers(NOW + timedelta(days=3650))

    def test_period_is_half_open(self) -> None:
        # The instant a period ends belongs to its successor, not to both.
        period = validate_effective_period(NOW, NOW + timedelta(days=1))
        assert period.covers(NOW)
        assert not period.covers(NOW + timedelta(days=1))

    def test_adjacent_periods_do_not_overlap(self) -> None:
        first = validate_effective_period(NOW, NOW + timedelta(days=1))
        second = validate_effective_period(NOW + timedelta(days=1), None)
        assert not first.overlaps(second)
        assert not second.overlaps(first)

    def test_open_ended_periods_overlap_everything_after_them(self) -> None:
        first = validate_effective_period(NOW, None)
        second = validate_effective_period(NOW + timedelta(days=365), None)
        assert first.overlaps(second)


class TestLifecycle:
    def test_draft_may_become_active(self) -> None:
        validate_transition(KnowledgeLifecycleState.DRAFT, KnowledgeLifecycleState.ACTIVE)

    def test_superseded_is_terminal(self) -> None:
        # Reviving one would mean two versions claiming to be current.
        with pytest.raises(InvalidLifecycleTransitionError):
            validate_transition(KnowledgeLifecycleState.SUPERSEDED, KnowledgeLifecycleState.ACTIVE)

    def test_archived_is_terminal(self) -> None:
        with pytest.raises(InvalidLifecycleTransitionError):
            validate_transition(KnowledgeLifecycleState.ARCHIVED, KnowledgeLifecycleState.ACTIVE)

    def test_draft_cannot_be_superseded(self) -> None:
        # Nothing was ever true, so nothing can replace it.
        with pytest.raises(InvalidLifecycleTransitionError):
            validate_transition(KnowledgeLifecycleState.DRAFT, KnowledgeLifecycleState.SUPERSEDED)


class TestProvenance:
    def test_publishing_needs_a_source(self) -> None:
        with pytest.raises(ProvenanceRequiredError):
            validate_publishable(source_document_version_id=None, source_reference=None)

    def test_blank_reference_is_not_a_source(self) -> None:
        with pytest.raises(ProvenanceRequiredError):
            validate_publishable(source_document_version_id=None, source_reference="   ")

    def test_a_reference_alone_is_enough(self) -> None:
        validate_publishable(source_document_version_id=None, source_reference="Price List 2026")


class TestSensitiveTypes:
    def test_price_and_sla_always_need_review(self) -> None:
        # Declared with the type rather than in the pipeline that will read
        # it, so a new sensitive type cannot be added without classifying
        # it. Nothing consults this in M2A; the assertion pins the
        # classification the ingestion phases will depend on.
        assert KnowledgeRecordType.PRICE in SENSITIVE_RECORD_TYPES
        assert KnowledgeRecordType.SLA_TERM in SENSITIVE_RECORD_TYPES
        assert KnowledgeRecordType.POLICY_PARAM in SENSITIVE_RECORD_TYPES
