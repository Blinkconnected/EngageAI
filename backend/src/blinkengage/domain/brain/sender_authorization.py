"""Who is allowed to teach a company's Brain.

Three conditions, all required, and none of them is "the address ends in the
right domain". A domain is not an identity: it is spoofable without DMARC, an
ex-employee keeps their address until somebody remembers to remove it, and a
compromised mailbox becomes a pricing channel. "From: CEO@company.com" is the
most attractive spoof target in the building, not the most trusted sender.

1. The address is on the company's own allowlist, which starts **empty**.
2. The message carries authentication results this platform can actually
   trust (below).
3. Nothing here makes knowledge authoritative. An authorized sender produces
   an accepted *source*; publication still needs a human and
   ``publication_gate()``.

**On trusting Authentication-Results.** The header is added by whichever MTA
performed the checks — and anyone can put one in a message they send. The only
one worth reading is the one stamped by a server we trust, identified by its
``authserv-id``. Blink connects to a mailbox it does not own, so it cannot know
that identifier by inspection: the company has to state it.

Absent that configuration there is no evidence, and this module says
``AUTHENTICATION_UNAVAILABLE`` rather than inventing confidence. It deliberately
does **not** perform DNS lookups against the sender's domain: "the domain
publishes a DMARC record" is a statement about the domain, not about this
message, and treating it as verification would be exactly the fake check the
architecture forbids.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class AuthenticationVerdict(StrEnum):
    """What a trusted verifier said about one mechanism."""

    PASS = "pass"
    FAIL = "fail"
    #: The verifier ran and reached no opinion — ``none``, ``neutral``,
    #: ``policy``, ``temperror``. Not a pass.
    INCONCLUSIVE = "inconclusive"
    #: No header from a trusted verifier was present at all.
    UNAVAILABLE = "unavailable"


class RejectionReason(StrEnum):
    """Why a message did not become a source. Deterministic, and internal.

    Never returned to a sender: telling an unauthorized address which of the
    three conditions it failed is a free oracle for finding the one that
    passes.
    """

    TENANT_UNRESOLVED = "TENANT_UNRESOLVED"
    INVALID_CHANNEL_PURPOSE = "INVALID_CHANNEL_PURPOSE"
    UNAUTHORIZED_SENDER = "UNAUTHORIZED_SENDER"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHENTICATION_UNAVAILABLE = "AUTHENTICATION_UNAVAILABLE"
    CREDENTIAL_MATERIAL = "CREDENTIAL_MATERIAL"
    MALFORMED_MESSAGE = "MALFORMED_MESSAGE"


@dataclass(frozen=True, slots=True)
class AuthenticationResults:
    """What a trusted verifier concluded about this message."""

    spf: AuthenticationVerdict = AuthenticationVerdict.UNAVAILABLE
    dkim: AuthenticationVerdict = AuthenticationVerdict.UNAVAILABLE
    dmarc: AuthenticationVerdict = AuthenticationVerdict.UNAVAILABLE
    #: The verifier whose header was read, when one was trusted.
    authserv_id: str | None = None

    @property
    def available(self) -> bool:
        return self.authserv_id is not None


@dataclass(frozen=True, slots=True)
class SenderDecision:
    """Accept or reject, and why."""

    accepted: bool
    reason: RejectionReason | None = None


_METHOD = re.compile(r"\b(?P<method>spf|dkim|dmarc)\s*=\s*(?P<result>[a-z]+)", re.IGNORECASE)

_VERDICTS: dict[str, AuthenticationVerdict] = {
    "pass": AuthenticationVerdict.PASS,
    "fail": AuthenticationVerdict.FAIL,
    "softfail": AuthenticationVerdict.FAIL,
    "permerror": AuthenticationVerdict.FAIL,
}


def normalise_address(address: str) -> str:
    """The comparable form of an email address.

    Case-folded and trimmed, and nothing else. Deliberately no gmail-style
    dot-stripping or ``+tag`` removal: those rules differ per provider, and a
    normaliser that is wrong about one provider silently widens an allowlist.
    """
    return address.strip().strip("<>").casefold()


def parse_authentication_results(
    headers: Sequence[str], *, trusted_authserv_id: str | None
) -> AuthenticationResults:
    """Read the results stamped by a verifier this company vouches for.

    Headers whose ``authserv-id`` does not match are ignored entirely — they
    may have been written by the sender. With no configured id, nothing is
    trusted and the result is unavailable rather than absent-and-assumed-fine.
    """
    if not trusted_authserv_id:
        return AuthenticationResults()

    expected = trusted_authserv_id.strip().casefold()
    for header in headers:
        authserv, separator, remainder = header.partition(";")
        if not separator or authserv.strip().casefold() != expected:
            continue
        found = {
            match.group("method").lower(): _VERDICTS.get(
                match.group("result").lower(), AuthenticationVerdict.INCONCLUSIVE
            )
            for match in _METHOD.finditer(remainder)
        }
        return AuthenticationResults(
            spf=found.get("spf", AuthenticationVerdict.UNAVAILABLE),
            dkim=found.get("dkim", AuthenticationVerdict.UNAVAILABLE),
            dmarc=found.get("dmarc", AuthenticationVerdict.UNAVAILABLE),
            authserv_id=trusted_authserv_id.strip(),
        )
    return AuthenticationResults()


def authenticated(results: AuthenticationResults) -> bool:
    """Did a trusted verifier establish that this message is from its domain?

    ``dmarc=pass`` on its own is sufficient: DMARC passes only on an aligned
    SPF or DKIM pass, which is the property being asserted. Failing that, an
    aligned pair of ``spf=pass`` and ``dkim=pass`` is accepted for verifiers
    that report the mechanisms without evaluating DMARC.
    """
    if results.dmarc is AuthenticationVerdict.PASS:
        return True
    return results.spf is AuthenticationVerdict.PASS and results.dkim is AuthenticationVerdict.PASS


def authorize_sender(
    *,
    sender: str,
    allowlisted: bool,
    results: AuthenticationResults,
) -> SenderDecision:
    """May this address contribute source material to this company?

    Order matters only for which reason is recorded, and the allowlist is
    checked first on purpose: an address nobody authorised is uninteresting
    whatever its headers say, and recording it as an authentication problem
    would send an operator to the wrong screen.
    """
    if not sender.strip():
        return SenderDecision(False, RejectionReason.MALFORMED_MESSAGE)

    if not allowlisted:
        return SenderDecision(False, RejectionReason.UNAUTHORIZED_SENDER)

    if not results.available:
        return SenderDecision(False, RejectionReason.AUTHENTICATION_UNAVAILABLE)

    if not authenticated(results):
        return SenderDecision(False, RejectionReason.AUTHENTICATION_FAILED)

    return SenderDecision(True)


__all__ = [
    "AuthenticationResults",
    "AuthenticationVerdict",
    "RejectionReason",
    "SenderDecision",
    "authenticated",
    "authorize_sender",
    "normalise_address",
    "parse_authentication_results",
]
