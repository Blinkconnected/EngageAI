"""Redacting a message: removing what was said, keeping that it was said.

Deletion was the obvious request and the wrong answer. A message sent
over WhatsApp, SMS or email **cannot be unsent** — the customer keeps
their copy whatever we do to ours. Deleting the row destroys our half of
a record the other half of which still exists, which is the worst of
both: we lose the ability to answer "what did we tell them?", and the
customer can still produce it.

Redaction keeps the shape of the conversation and removes the content.
The message stays in the thread, in order, attributed, timestamped, and
marked as redacted. What it said is gone, and *who removed it and why*
is permanently on the record.

Nothing here touches the database. These are the rules, stated where
they can be read and tested as rules.
"""

from dataclasses import dataclass
from enum import StrEnum

#: The reason is read by an auditor, often long after everyone involved
#: has left. Long enough to be a sentence rather than a word.
MIN_REASON_LENGTH = 10

MAX_REASON_LENGTH = 2000

#: Shown in the thread where the content used to be. Deliberately plain:
#: an agent reading back through a conversation should understand
#: immediately, without a legend.
REDACTED_PLACEHOLDER = "Message redacted"


class RedactionRuleViolation(Exception):
    """A rule was broken. Carries a code the API maps to a status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RedactionOutcome:
    """What a redaction actually removed, for the audit record.

    Counted rather than described: "3 attachments purged" is checkable
    against object storage years later, where "attachments removed" is
    not.
    """

    attachments_purged: int
    memory_evidence_removed: int
    learning_observations_detached: int


def validate_reason(reason: str) -> str:
    """The reason, normalised — or a violation saying what is wrong.

    Whitespace is collapsed before measuring, so a field of spaces is an
    empty field rather than a long one.
    """
    cleaned = " ".join(reason.split())
    if len(cleaned) < MIN_REASON_LENGTH:
        raise RedactionRuleViolation(
            code="reason_too_short",
            message=(
                f"Say why this message is being redacted, in at least "
                f"{MIN_REASON_LENGTH} characters. Redaction cannot be undone, and "
                f"this sentence is the whole of what an auditor will have."
            ),
        )
    if len(cleaned) > MAX_REASON_LENGTH:
        raise RedactionRuleViolation(
            code="reason_too_long",
            message=f"Keep the reason under {MAX_REASON_LENGTH} characters.",
        )
    return cleaned


def ensure_not_already_redacted(redacted_at: object) -> None:
    """Redacting twice is not idempotent, it is a second audit entry.

    The content is already gone, so a repeat does nothing useful and
    writes a second record with a different actor and reason against the
    same removal — two accounts of one event, which is worse than one.

    This also makes the endpoint safe to retry: a duplicate delivery gets
    a clean conflict rather than silently appending to the audit trail.
    """
    if redacted_at is not None:
        raise RedactionRuleViolation(
            code="already_redacted",
            message="This message has already been redacted.",
        )


#: Keys in ``message_metadata`` that are safe to keep, because they carry
#: no customer content and the conversation stops making sense without
#: them.
#:
#: An allow-list, not a deny-list. Providers add fields, workflows write
#: their own, and a deny-list silently leaks every key nobody thought of
#: — which for this table means leaking the content redaction was
#: supposed to remove.
METADATA_KEYS_KEPT = frozenset(
    {
        "is_ai_generated",  # provenance: was a human in the loop
        "error",  # why a send failed; no customer content
        "provider",
        "channel_type",
        "delivery_attempts",
    }
)


def strip_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Everything except the allow-list above.

    Provider payloads routinely echo the message body back — a WhatsApp
    delivery receipt carries the text, an email metadata blob carries the
    subject and often a quoted reply. Redacting ``body`` and leaving
    ``message_metadata`` intact would remove the content from the screen
    and leave it in the database, the API response and every export.
    """
    return {key: value for key, value in metadata.items() if key in METADATA_KEYS_KEPT}


class RedactionScope(StrEnum):
    """What a redaction covers.

    Only one member today. It exists so the audit row records the scope
    explicitly rather than implying it — a later "redact the attachment
    but keep the text" would otherwise be indistinguishable in the record
    from today's behaviour.
    """

    MESSAGE_AND_ATTACHMENTS = "message_and_attachments"


__all__ = [
    "MAX_REASON_LENGTH",
    "METADATA_KEYS_KEPT",
    "MIN_REASON_LENGTH",
    "REDACTED_PLACEHOLDER",
    "RedactionOutcome",
    "RedactionRuleViolation",
    "RedactionScope",
    "ensure_not_already_redacted",
    "strip_metadata",
    "validate_reason",
]
