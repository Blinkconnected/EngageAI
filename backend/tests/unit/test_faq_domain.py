"""The FAQ contract, in isolation.

Pure rules with no database, so what is asserted here is the shape a
stored FAQ is guaranteed to have — not what one particular code path
happens to do today.
"""

from uuid import uuid4

import pytest

from blinkengage.domain.faq import (
    DEFAULT_IS_PUBLISHED,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    FaqAnswerRequiredError,
    FaqContent,
    FaqQuestionRequiredError,
    FaqTooLongError,
    UnknownLocaleError,
    embeddable_text,
    next_display_order,
    normalise_locale,
    reordered,
    validate_content,
)


class TestTheContract:
    def test_a_question_and_an_answer_are_both_required(self) -> None:
        validate_content(FaqContent(question="Do you deliver?", answer="Yes, within 3 days."))

        with pytest.raises(FaqQuestionRequiredError):
            validate_content(FaqContent(question="   ", answer="Yes."))
        with pytest.raises(FaqAnswerRequiredError):
            validate_content(FaqContent(question="Do you deliver?", answer=" "))

    def test_length_is_bounded_so_an_faq_stays_an_faq(self) -> None:
        """Anything longer is an article, and the platform already has
        those. The bound is what stops the FAQ table quietly becoming a
        second, worse knowledge base."""
        with pytest.raises(FaqTooLongError) as question_exc:
            validate_content(FaqContent(question="q" * (MAX_QUESTION_CHARS + 1), answer="ok"))
        assert question_exc.value.field == "question"

        with pytest.raises(FaqTooLongError) as answer_exc:
            validate_content(FaqContent(question="q", answer="a" * (MAX_ANSWER_CHARS + 1)))
        assert answer_exc.value.field == "answer"

    def test_an_faq_is_created_unpublished(self) -> None:
        """The asymmetry with knowledge articles is the point.

        An unfinished article is seen by agents, who can tell a draft
        from a policy. An unfinished FAQ is seen by customers, who
        cannot.
        """
        assert DEFAULT_IS_PUBLISHED is False


class TestWhatGetsEmbedded:
    def test_both_the_question_and_the_answer_are_embedded(self) -> None:
        """Question-only embedding makes an FAQ unfindable by a term that
        appears solely in its answer — a product name, a fee, a branch —
        which is a large share of what customers actually type."""
        text = embeddable_text(
            FaqContent(question="How do I pay?", answer="By Visa, Mastercard or eFAWATEERcom.")
        )

        assert "How do I pay?" in text
        assert "eFAWATEERcom" in text

    def test_the_embeddable_text_is_stable_under_surrounding_whitespace(self) -> None:
        """The content hash is computed over this string, so a stray
        trailing newline must not make an unchanged FAQ look changed and
        turn every sweep into a paid re-embedding."""
        a = embeddable_text(FaqContent(question="  Do you deliver? ", answer="Yes.\n"))
        b = embeddable_text(FaqContent(question="Do you deliver?", answer="Yes."))

        assert a == b


class TestLocale:
    def test_a_locale_folds_onto_the_supported_set(self) -> None:
        assert normalise_locale("EN") == "en"
        assert normalise_locale("en-GB") == "en"
        assert normalise_locale("ar") == "ar"

    def test_no_locale_is_a_real_answer(self) -> None:
        """A price or a phone number applies whatever the customer
        speaks, and should not be forced to pick a language."""
        assert normalise_locale(None) is None
        assert normalise_locale("  ") is None

    def test_an_unsupported_locale_is_refused_rather_than_stored(self) -> None:
        """A silently accepted 'fr' produces an FAQ no language filter
        ever returns, which looks exactly like the FAQ having been lost."""
        with pytest.raises(UnknownLocaleError):
            normalise_locale("fr")


class TestOrdering:
    def test_a_new_faq_is_appended_not_prepended(self) -> None:
        """The order is somebody's editorial decision; a new entry taking
        the first slot would rewrite it."""
        assert next_display_order([]) == 0
        assert next_display_order([0, 1, 2]) == 3

    def test_reordering_moves_only_the_ids_it_names(self) -> None:
        """Partial by design: reordering the five FAQs on one filtered
        screen must not reshuffle the forty that screen never loaded."""
        a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()

        positions = reordered(current=[a, b, c, d], ordered_ids=[c, a])

        assert positions[c] == 0
        assert positions[a] == 1
        # b and d keep their relative order, behind the named ones.
        assert positions[b] < positions[d]
        assert positions[b] >= 2

    def test_an_unknown_id_in_a_reorder_is_ignored_not_fatal(self) -> None:
        """A stale browser tab holding a deleted FAQ's id must not make
        the whole reorder fail."""
        a, b = uuid4(), uuid4()

        positions = reordered(current=[a, b], ordered_ids=[b, uuid4()])

        assert set(positions) == {a, b}
        assert positions[b] == 0
