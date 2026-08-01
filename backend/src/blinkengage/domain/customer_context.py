"""The Customer Context: who this conversation is with, frozen at one version.

The counterpart to ``ServiceContext``. That one says how the business behaves;
this one says how *this customer* is treated — their tier, their language,
whether they are a named account, which contract they are on, who they usually
speak to.

Same two rules, for the same reasons. It is resolved **once**, at the start,
and every module downstream receives the object rather than a ``customer_id``,
so nothing can look the customer up again mid-execution and read something
different. And it is **immutable**: a customer upgraded to VIP at noon does not
retroactively change how the conversation opened that morning was routed, or
what an agent was told about them while working it.

There is one hazard here that the Service Context does not have, and it shapes
the whole design.

A service changes when an administrator edits it: rarely, and deliberately. A
customer record changes constantly — a CRM sync writes a field back, an agent
corrects a phone number, ``last_seen_at`` is touched on every visit. Minting a
version on *every* change would produce one version per conversation and a
chain nobody could read, which is the same as having no versioning at all.

So a version is minted from a **fingerprint of the routing-relevant attributes
only**. Everything below is something that changes how a conversation is
handled; nothing below is a field that merely moves. If the fingerprint matches
the current version, that version is reused and no row is written. Renaming a
customer therefore does not fork their history; promoting them to VIP does.

Framework-free, like the rest of ``domain/``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CustomerTier(StrEnum):
    """How much attention this customer's conversations get.

    A closed set rather than free text because routing, SLA selection and
    overflow all branch on it, and a tier nothing recognises is a tier that
    silently behaves like the default.
    """

    STANDARD = "standard"
    PRIORITY = "priority"
    VIP = "vip"
    #: Named accounts with individual contracts — treated as VIP for routing
    #: but distinguished so reporting can separate them.
    STRATEGIC = "strategic"


class ContactPreference(StrEnum):
    """How a customer has asked to be contacted."""

    ANY = "any"
    SAME_CHANNEL = "same_channel"
    EMAIL_ONLY = "email_only"
    NO_AUTOMATED_MESSAGES = "no_automated_messages"


@dataclass(frozen=True, slots=True)
class CustomerContext:
    """Everything about the customer that changes how a conversation runs.

    Deliberately **not** a copy of the customer record. It carries what
    routing, SLA, AI and reporting branch on, and nothing else: an address,
    a phone number and a notes field belong to the customer profile, which a
    module can open if a human asks to see it. Copying them here would make
    every profile edit look like a routing-relevant change, and would put
    personal data into an immutable versioned store that has no business
    holding it.
    """

    customer_id: uuid.UUID
    #: Monotonic per customer, starting at 1.
    version: int
    customer_version_id: uuid.UUID
    company_id: uuid.UUID

    #: Carried as a value so a conversation can say who it is with even
    #: after the customer is renamed or erased.
    display_name: str

    tier: CustomerTier = CustomerTier.STANDARD
    #: A separate flag from ``tier`` on purpose: a company can mark somebody
    #: VIP for a single campaign without moving their commercial tier, and
    #: routing wants to know about both.
    is_vip: bool = False

    #: BCP-47 where known. Drives language-based routing and which AI prompt
    #: is used. ``None`` means undetected, not English.
    language: str | None = None
    #: IANA name. What "within business hours" means *for them*, which is
    #: not always what it means for the service.
    timezone: str | None = None
    country_code: str | None = None

    #: Commercial position, carried as values. The billing domain owns these
    #: objects; a routing context that held live references to them would be
    #: a second place billing configuration could be read from.
    contract_id: uuid.UUID | None = None
    contract_name: str | None = None
    pricing_profile_id: uuid.UUID | None = None
    #: Free-form grouping a company uses for its own reporting.
    segment: str | None = None

    contact_preference: ContactPreference = ContactPreference.ANY

    #: Who this customer usually speaks to. Advisory: it is an input to
    #: routing, not an instruction, because the agent may be unavailable and
    #: a conversation that waits for one specific person is a conversation
    #: nobody answers.
    preferred_agent_id: uuid.UUID | None = None

    #: Where attributes that do not exist yet live. Same seam, same reason,
    #: same behaviour as ``ServiceContext.extras`` — a version written before
    #: an attribute existed answers with the caller's default rather than
    #: raising.
    extras: dict[str, Any] = field(default_factory=dict)

    def attribute(self, namespace: str, key: str, default: Any = None) -> Any:
        """One future attribute, or ``default`` if this version predates it."""
        section = self.extras.get(namespace)
        if not isinstance(section, dict):
            return default
        return section.get(key, default)

    @property
    def deserves_priority(self) -> bool:
        """Whether routing should treat this customer as ahead of the queue.

        One question, asked in one place, so the VIP lane and the priority
        lane and the SLA selection cannot each answer it slightly
        differently.
        """
        return self.is_vip or self.tier in (CustomerTier.VIP, CustomerTier.STRATEGIC)


#: The attributes a version is minted from. Everything here changes how a
#: conversation is handled; a change to anything *not* here must not fork a
#: customer's history. Adding a field to this tuple is a deliberate act with a
#: cost: every customer's next conversation mints a new version.
ROUTING_RELEVANT_FIELDS: tuple[str, ...] = (
    "tier",
    "is_vip",
    "language",
    "timezone",
    "country_code",
    "contract_id",
    "pricing_profile_id",
    "segment",
    "contact_preference",
    "preferred_agent_id",
)


def fingerprint(
    *,
    tier: CustomerTier = CustomerTier.STANDARD,
    is_vip: bool = False,
    language: str | None = None,
    timezone: str | None = None,
    country_code: str | None = None,
    contract_id: uuid.UUID | None = None,
    pricing_profile_id: uuid.UUID | None = None,
    segment: str | None = None,
    contact_preference: ContactPreference = ContactPreference.ANY,
    preferred_agent_id: uuid.UUID | None = None,
    extras: dict[str, Any] | None = None,
) -> str:
    """A stable digest of the routing-relevant attributes.

    Used to decide whether a customer's current profile still matches their
    latest version. Equal fingerprint means reuse the version and write
    nothing; different means mint a new one.

    **Stable across processes and releases.** Python's ``hash()`` is salted
    per process and would silently fork every customer's history on restart,
    so this is a SHA-256 over a canonically ordered JSON rendering. The
    values are stringified rather than trusted to serialise: a ``UUID`` and
    its string form must produce the same digest, or a change of type
    somewhere upstream would look like a change of customer.
    """
    payload = {
        "tier": str(tier),
        "is_vip": bool(is_vip),
        "language": _text(language),
        "timezone": _text(timezone),
        "country_code": _text(country_code),
        "contract_id": _text(contract_id),
        "pricing_profile_id": _text(pricing_profile_id),
        "segment": _text(segment),
        "contact_preference": str(contact_preference),
        "preferred_agent_id": _text(preferred_agent_id),
        # Sorted so two dicts with the same content in a different insertion
        # order do not mint a version apiece.
        "extras": _canonical(extras or {}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: object) -> str | None:
    """``None`` stays ``None``; everything else becomes its string form.

    An empty string and ``None`` are folded together deliberately: a field
    cleared to "" and one never set describe the same customer, and treating
    them as different would mint a version for a whitespace edit.
    """
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _canonical(value: Any) -> Any:
    """Nested structures in a form two equal dicts always agree on."""
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def matches(context: CustomerContext, current_fingerprint: str) -> bool:
    """Whether a bound context still reflects the customer as they are now.

    Not a correctness check — a context that no longer matches is the
    guarantee working, exactly as with a stale service version. It is what
    the console shows when somebody asks why a conversation opened this
    morning is not being treated as VIP after the upgrade at noon.
    """
    return bool(context.attribute("_meta", "fingerprint") == current_fingerprint)


__all__ = [
    "ROUTING_RELEVANT_FIELDS",
    "ContactPreference",
    "CustomerContext",
    "CustomerTier",
    "fingerprint",
    "matches",
]
