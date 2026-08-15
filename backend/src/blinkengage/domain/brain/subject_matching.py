"""Which subject is this customer asking about?

A price is retrieved by identity, not by resemblance: "what does DIA 500 Mbps
cost?" answered by cosine similarity returns the 200 Mbps row with a
respectable score, and the customer is quoted the wrong number confidently.

So the match is deterministic and reuses the canonicaliser the records were
written with. A subject matches when its key's tokens appear **contiguously**
in the canonicalised question — the same folding, the same digit mapping, the
same Arabic normalisation, so ``خدمة ٥٠٠`` in a question finds the record
written as ``خدمه-500``.

No model, for the reason ``canonical_subject_key`` gives: a key that differs
between runs forks one product's history into two chains. The same argument
applies to the lookup — a match that differs between runs quotes a different
price on Tuesday.

This is the narrow, rules-first half of the retrieval router (M2C). It answers
"does the company have a record for something named in this question?" and
nothing else. Intent classification, aliases and the model fallback are that
milestone's work, not this one.
"""

from __future__ import annotations

from collections.abc import Iterable

from blinkengage.domain.knowledge_records import (
    KnowledgeRecordError,
    canonical_subject_key,
)


def query_tokens(query: str) -> tuple[str, ...]:
    """The question, folded through the subject canonicaliser.

    Returns empty rather than raising for a question with no letters or
    digits — "???" is a question the platform cannot match a subject in, not
    an error. ``canonical_subject_key`` raises there because a *record* with
    no derivable key is a defect; a *query* with none is Tuesday.
    """
    try:
        return tuple(canonical_subject_key(query).split("-"))
    except KnowledgeRecordError:
        return ()


def subject_tokens(subject_key: str) -> tuple[str, ...]:
    """A stored key split back into its tokens."""
    return tuple(token for token in subject_key.split("-") if token)


def matches(subject_key: str, tokens: tuple[str, ...]) -> bool:
    """Does this subject appear in the tokenised question?

    Contiguous, in order. ``dia-500-mbps`` matches "how much is DIA 500 Mbps"
    and does **not** match "is DIA available at 500 sites in mbps terms" —
    a bag-of-words match would accept the second, and the whole point of
    identity retrieval is that it declines to guess.
    """
    needle = subject_tokens(subject_key)
    if not needle or len(needle) > len(tokens):
        return False
    return any(
        tokens[start : start + len(needle)] == needle
        for start in range(len(tokens) - len(needle) + 1)
    )


def match_subjects(query: str, subject_keys: Iterable[str]) -> tuple[str, ...]:
    """Every known subject named in the question, longest first.

    Longest first because a company with both ``dia`` and ``dia-500-mbps``
    asked about the latter has named both, and the more specific record is
    the one that answers the question. Ordering here rather than at the call
    site keeps the tie-break in one place.
    """
    tokens = query_tokens(query)
    if not tokens:
        return ()
    found = {key for key in subject_keys if matches(key, tokens)}
    return tuple(sorted(found, key=lambda key: (-len(subject_tokens(key)), key)))


def rank_subjects(query: str, subject_keys: Iterable[str]) -> tuple[str, ...]:
    """Subjects a *browsing* search should return, best first.

    A second question for the same matcher, not a second matcher.
    :func:`match_subjects` answers "which subject did this sentence name?",
    and its contiguity rule is what stops a customer's question being
    answered with a neighbouring product's price. That rule is exactly wrong
    for an administrator typing ``prices`` or ``dia`` into an assistant: they
    are looking for a record to talk about, not quoting one, and a matcher
    that returns nothing unless the whole key was spelled out cannot find it.

    So the ordering is: everything :func:`match_subjects` would accept, first
    and in its own precedence, then partial overlaps by how much of the
    subject the query actually named. Nothing new decides *what a subject
    is* — the tokens come from the same canonicaliser the records were
    written with.

    This never grants authority. Authority comes from ``resolve``, which
    takes an exact key and is untouched by anything here; a looser search
    that fed an answer would be the failure this module's docstring opens
    with.
    """
    tokens = query_tokens(query)
    if not tokens:
        return ()

    asked = set(tokens)
    scored: list[tuple[int, int, str]] = []
    for key in dict.fromkeys(subject_keys):
        needle = subject_tokens(key)
        if not needle:
            continue
        if matches(key, tokens):
            # Named outright. Ranked above every partial hit, and among
            # themselves longest-first — the same tie-break match_subjects
            # applies, for the same reason.
            scored.append((1, len(needle), key))
            continue
        overlap = len(asked & set(needle))
        if overlap:
            scored.append((0, overlap, key))

    return tuple(key for _, _, key in sorted(scored, key=lambda hit: (-hit[0], -hit[1], hit[2])))


__all__ = ["match_subjects", "matches", "query_tokens", "rank_subjects", "subject_tokens"]
