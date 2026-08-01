"""Request/response schemas for installation-level settings.

The SMTP password is **write-only**: it is accepted on the way in and
never sent back. An operator who can read a credential off a screen has
a way to exfiltrate it, and there is no legitimate reason to need it
again once it is set.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from blinkengage.domain.mail import MailSecurity

#: A deliberately permissive sender-address check, rather than
#: ``EmailStr``. Pydantic's validator rejects special-use domains, and
#: this installation's own shipped default is
#: ``notifications@blinkengage.local`` — so an operator on a fresh
#: install who changed only the host would be refused because of a
#: field they never touched. Internal relays legitimately send from
#: ``.local`` and ``.internal``, and the authority on whether an
#: envelope sender is acceptable is the relay, which says so in the
#: test-send result.
_ADDRESS = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MailSettingsResponse(BaseModel):
    host: str
    port: int
    security: MailSecurity
    from_address: str
    from_name: str
    username: str | None
    #: Whether *a* password is configured. A blank field otherwise means
    #: two different things — "no authentication" and "authenticated,
    #: but hidden" — and an operator cannot tell which without sending.
    password_set: bool
    timeout_seconds: int
    #: False when these values come from environment variables, so an
    #: operator reading unfamiliar settings knows whether they arrived
    #: from a deploy or from somebody editing this form.
    customised: bool
    updated_by_email: str | None
    updated_at: datetime | None


class MailSettingsRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    security: MailSecurity
    from_address: str = Field(pattern=_ADDRESS, max_length=255)
    from_name: str = Field(min_length=1, max_length=120)
    username: str | None = Field(default=None, max_length=255)
    #: Omit to keep the stored password; send an empty string to clear
    #: it. The distinction is deliberate — the form never receives the
    #: password back, so a naive round-trip would otherwise erase it.
    password: str | None = Field(default=None, max_length=500)
    timeout_seconds: int = Field(default=15, ge=1, le=120)


class TestMailRequest(BaseModel):
    # Same permissive check as the sender, for the same reason: an
    # operator verifying an internal relay may legitimately send to
    # an internal address, and the relay is the authority on whether
    # it will accept one.
    to_address: str = Field(pattern=_ADDRESS, max_length=255)


class TestMailResponse(BaseModel):
    delivered: bool
    #: The relay's own words when it refused — "535 authentication
    #: failed" tells an operator to fix the password, while "could not
    #: send email" sends them looking at DNS.
    detail: str | None = None


__all__ = [
    "MailSettingsRequest",
    "MailSettingsResponse",
    "TestMailRequest",
    "TestMailResponse",
]


# --- Payment providers -----------------------------------------------


class CredentialFieldResponse(BaseModel):
    """One box on the provider's form.

    The form is described by the backend rather than hardcoded in the
    console: a field the backend requires and the form does not render is
    a provider that can never be saved.
    """

    name: str
    label: str
    secret: bool
    required: bool
    help_text: str | None = None
    choices: list[str] = []


class PaymentProviderResponse(BaseModel):
    kind: str
    label: str
    description: str
    #: How the customer actually pays — redirect, bill presentment, credit
    #: transfer or operator entry. Decides what the console explains.
    flow: str
    countries: list[str]
    fields: list[CredentialFieldResponse]
    enabled: bool
    #: ``active`` / ``not_configured`` / ``awaiting_integration``.
    readiness: str
    #: Required fields with nothing in them, so the console can point at
    #: them rather than saying "invalid".
    missing: list[str]
    #: Which secrets have a value — never the values themselves.
    secret_set: dict[str, bool]
    #: Everything that is not a secret.
    values: dict[str, Any]
    #: Why this cannot be connected yet, when it cannot.
    pending_note: str | None = None


class PaymentProvidersResponse(BaseModel):
    providers: list[PaymentProviderResponse]
    updated_by_email: str | None
    updated_at: datetime | None


class PaymentProviderRequest(BaseModel):
    enabled: bool = False
    #: A secret omitted (or sent as null) is left unchanged; sent as ""
    #: it is cleared. The console is never given a stored secret back, so
    #: treating absence as "clear" would erase credentials on every save.
    values: dict[str, Any] = {}
