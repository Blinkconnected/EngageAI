"""The rules that decide what redaction removes.

The metadata allow-list is the one worth reading twice. Provider
payloads echo the message back — a WhatsApp receipt carries the text, an
email blob carries the subject and the quoted reply — so a redaction
that clears `body` and leaves `message_metadata` has removed the content
from the screen and left it in the database, the API and every export.
"""

import pytest

from blinkengage.domain.message_redaction import (
    METADATA_KEYS_KEPT,
    MIN_REASON_LENGTH,
    RedactionRuleViolation,
    ensure_not_already_redacted,
    strip_metadata,
    validate_reason,
)


class TestTheReason:
    def test_a_real_reason_survives(self) -> None:
        assert validate_reason("Card details pasted by mistake") == (
            "Card details pasted by mistake"
        )

    def test_whitespace_is_collapsed_before_measuring(self) -> None:
        with pytest.raises(RedactionRuleViolation) as caught:
            validate_reason(" " * (MIN_REASON_LENGTH + 20))

        assert caught.value.code == "reason_too_short"

    def test_one_word_is_refused(self) -> None:
        # An auditor reading this years later has only this sentence.
        with pytest.raises(RedactionRuleViolation) as caught:
            validate_reason("pii")

        assert caught.value.code == "reason_too_short"

    def test_the_message_says_it_cannot_be_undone(self) -> None:
        with pytest.raises(RedactionRuleViolation) as caught:
            validate_reason("no")

        assert "cannot be undone" in str(caught.value)


class TestRedactingTwice:
    def test_an_unredacted_message_may_be_redacted(self) -> None:
        ensure_not_already_redacted(None)

    def test_a_redacted_message_may_not(self) -> None:
        """The content is already gone, so a repeat does nothing useful
        and writes a second account of one removal — with a different
        actor and a different reason."""
        from datetime import UTC, datetime

        with pytest.raises(RedactionRuleViolation) as caught:
            ensure_not_already_redacted(datetime.now(UTC))

        assert caught.value.code == "already_redacted"


class TestTheMetadataAllowList:
    def test_provider_echoes_of_the_body_are_removed(self) -> None:
        secret = "card 4111 1111 1111 1111"
        stripped = strip_metadata(
            {
                "raw": {"text": secret},
                "whatsapp_payload": secret,
                "subject": secret,
                "quoted_reply": secret,
            }
        )

        assert stripped == {}
        assert secret not in str(stripped)

    def test_provenance_and_delivery_facts_are_kept(self) -> None:
        """The conversation stops making sense without them, and none of
        them carries customer content."""
        kept = strip_metadata(
            {
                "is_ai_generated": True,
                "error": "Recipient rejected the message",
                "provider": "whatsapp",
                "delivery_attempts": 3,
                "body_copy": "secret",
            }
        )

        assert kept == {
            "is_ai_generated": True,
            "error": "Recipient rejected the message",
            "provider": "whatsapp",
            "delivery_attempts": 3,
        }

    def test_it_is_an_allow_list_not_a_deny_list(self) -> None:
        """The property that matters.

        Providers add fields and workflows write their own. A deny-list
        silently leaks every key nobody thought of, which for this table
        means leaking exactly the content redaction was meant to remove.
        """
        stripped = strip_metadata({f"unknown_field_{n}": "secret" for n in range(50)})

        assert stripped == {}

    def test_the_allow_list_holds_nothing_content_shaped(self) -> None:
        # A guard on the list itself: adding "body" or "text" here would
        # quietly undo the feature.
        assert not {"body", "text", "raw", "subject", "content"} & METADATA_KEYS_KEPT

    def test_empty_metadata_is_handled(self) -> None:
        assert strip_metadata({}) == {}
