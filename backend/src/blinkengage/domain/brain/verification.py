"""The last gate before a company fact reaches a customer.

Phase 2 gave Autopilot the company's approved records and told the model to
quote them exactly. That is grounding, and grounding is a *request*. This is
the enforcement: a generated reply that states a figure the company never
approved does not get sent, whatever the model's confidence in it.

The distinction matters because the failure is invisible from the inside. A
model handed an absence signal usually says "I don't have that on record" —
and occasionally says "I believe it's around 120 JOD", fluently, at high
confidence, in the customer's own dialect. Nothing downstream can tell those
two apart, because both are well-formed replies from a model that was asked
nicely.

**What this verifies, and what it does not.** It verifies *value claims* —
figures — about subjects the company keeps authoritative records for. That is
deliberately narrow and it is the narrowest thing that closes the actual hole:
prices, SLA terms and policy parameters are the sensitive record types, they
are numeric, and a wrong number is the failure that costs money and trust. It
does **not** attempt to verify prose. "Our support team is famously helpful" is
unverifiable without a model reading it, and this file does not add one.

Non-goals, stated because a verifier that creeps becomes one people switch off:

- Not a hallucination detector. Generic conversation is not its business.
- Not a keyword matcher. It never looks for "price" or "JOD"; it compares
  figures against what the company approved.
- Not a second opinion on the model's confidence. That gate already exists,
  runs first, and is untouched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class VerificationOutcome(StrEnum):
    """What may happen to this reply."""

    #: Send it. Either nothing in it needs authority, or everything that does
    #: has it.
    ALLOW = "ALLOW"
    #: Do not send it. The reply asserts something the company has not
    #: approved.
    BLOCK = "BLOCK"
    #: Do not send it, and a human is specifically the right answer — the
    #: company's own records disagree, or the platform could not check.
    ESCALATE = "ESCALATE"


class VerificationReason(StrEnum):
    """Why, in a form a dashboard and a person can both read."""

    #: Every figure in the reply traces to an approved record.
    AUTHORITY_CONFIRMED = "AUTHORITY_CONFIRMED"
    #: The reply asserts no company figure, so there is nothing to support.
    NO_COMPANY_CLAIM = "NO_COMPANY_CLAIM"
    #: The platform checked and the company has no approved record.
    AUTHORITY_ABSENT = "AUTHORITY_ABSENT"
    #: The company's own records disagree. Never resolved automatically.
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    #: The platform could not check. **Not** the same as having checked and
    #: found nothing, and the two must never be reported as one: "we do not
    #: offer that" and "our knowledge store is down" are different sentences
    #: to a customer and different problems to an operator.
    GROUNDING_UNAVAILABLE = "GROUNDING_UNAVAILABLE"
    #: A record was found, and the reply quotes a figure that is not in it.
    UNSUPPORTED_VALUE = "UNSUPPORTED_VALUE"


@dataclass(frozen=True, slots=True)
class GroundingFacts:
    """What the Brain established for this turn. Inputs, not opinions."""

    #: The question named a subject whose type only an approved record may
    #: answer — a price, an SLA term, a policy parameter.
    requires_authority: bool = False
    #: Approved records resolved for it.
    authoritative_hits: int = 0
    #: Two records claim one subject over one instant.
    conflicted: bool = False
    #: The lookup itself failed. Distinct from finding nothing.
    unavailable: bool = False
    #: Every figure the company has approved for this turn — from the
    #: resolved records' attributes and their subject labels.
    #:
    #: Deliberately **not** seeded from the customer's message. A customer who
    #: asks "is it 120 JOD?" would otherwise authorise the reply "yes, 120
    #: JOD" by having said the number first, which is the cheapest possible
    #: way to make a platform quote a price it never approved.
    supported_values: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    """The decision, and enough of the reasoning to act on it."""

    outcome: VerificationOutcome
    reason: VerificationReason
    #: Figures in the reply that nothing approved. Never shown to a customer;
    #: this is for the operator reading why a reply was withheld.
    unsupported_values: tuple[str, ...] = ()

    @property
    def may_send(self) -> bool:
        return self.outcome is VerificationOutcome.ALLOW


#: A run of digits, with optional decimal part. Applied *after* folding, so
#: Arabic-Indic digits are already ASCII by the time this runs.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _fold(text: str) -> str:
    """Digits to ASCII, and nothing else touched.

    Deliberately *not* ``canonical_subject_key``. That folds punctuation into
    separators, which is right for a subject key and wrong here: it splits
    ``180.00`` into ``180`` and ``00``, so a record of 180 would be reported
    as unsupported by a reply saying 180.00 — withholding a correct answer,
    which is how a safety control earns a reputation for being wrong.

    ``unicodedata.digit`` covers every decimal digit Unicode defines, so
    Arabic-Indic ``١٨٠`` and Eastern Arabic ``۱۸۰`` both arrive as ``180``
    without enumerating scripts.
    """
    normalised = unicodedata.normalize("NFKC", text)
    return "".join(
        str(unicodedata.digit(character)) if character.isdigit() else character
        for character in normalised
    )


def _normalise(number: str) -> str:
    """One spelling per figure, so ``180``, ``180.0`` and ``180,00`` agree.

    Without this the verifier reports a record of ``180`` as unsupported by a
    reply saying ``180.00`` — blocking a correct answer, which is the failure
    that gets a safety control disabled.
    """
    cleaned = number.replace(",", ".")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def value_claims(text: str) -> frozenset[str]:
    """Every figure asserted in a piece of text, normalised.

    Deliberately not "every company fact". A figure is the part of a company
    claim that can be checked against a record without a model reading the
    sentence, and prices, SLA terms and policy parameters — the three types
    that require approval — are figures.
    """
    return frozenset(_normalise(match.group()) for match in _NUMBER.finditer(_fold(text)))


def verify_reply(reply: str, facts: GroundingFacts) -> VerificationVerdict:
    """May this reply be sent?

    Evaluated in the order the failures matter, and the order is the point:

    1. **Nothing needs authority** — the question named no priced or
       parametric subject, so this is ordinary conversation and none of the
       verifier's business. Blocking here would make it a hallucination
       detector, which it is not.
    2. **The reply asserts no figure** — a deferral ("let me confirm that and
       come back to you") is exactly the behaviour the absence signal asks
       for, and refusing to send it would punish the model for doing the
       right thing.
    3. **Conflict** — escalate, always, and state nothing. Picking the higher
       score turns a data problem into a quotation.
    4. **Could not check** — escalate. Failing closed, and reported as its own
       reason so nobody tells a customer "we don't have that" when the truth
       is "we could not look".
    5. **Checked, nothing found** — block. The figure came from somewhere the
       company never approved.
    6. **Found, and the figure is not in it** — block. This is the case the
       whole file exists for: an approved record of 180 and a reply of 120.
    """
    if not facts.requires_authority:
        return VerificationVerdict(VerificationOutcome.ALLOW, VerificationReason.NO_COMPANY_CLAIM)

    claimed = value_claims(reply)
    if not claimed:
        return VerificationVerdict(VerificationOutcome.ALLOW, VerificationReason.NO_COMPANY_CLAIM)

    if facts.conflicted:
        return VerificationVerdict(
            VerificationOutcome.ESCALATE, VerificationReason.AUTHORITY_CONFLICT
        )

    if facts.unavailable:
        return VerificationVerdict(
            VerificationOutcome.ESCALATE, VerificationReason.GROUNDING_UNAVAILABLE
        )

    if facts.authoritative_hits == 0:
        return VerificationVerdict(
            VerificationOutcome.BLOCK,
            VerificationReason.AUTHORITY_ABSENT,
            tuple(sorted(claimed)),
        )

    unsupported = claimed - facts.supported_values
    if unsupported:
        return VerificationVerdict(
            VerificationOutcome.BLOCK,
            VerificationReason.UNSUPPORTED_VALUE,
            tuple(sorted(unsupported)),
        )

    return VerificationVerdict(VerificationOutcome.ALLOW, VerificationReason.AUTHORITY_CONFIRMED)


__all__ = [
    "GroundingFacts",
    "VerificationOutcome",
    "VerificationReason",
    "VerificationVerdict",
    "value_claims",
    "verify_reply",
]
