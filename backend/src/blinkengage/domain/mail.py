"""The outbound mail relay's configuration.

See ``docs/architecture/platform-admin.md``.

Framework-free, like the rest of ``domain/``: a dataclass and the rules
for combining a stored configuration with the environment defaults.

The **resolution rule** is the interesting part. SMTP has always been
configured by environment variable, and existing installations depend on
that. So the stored configuration *overrides* the environment rather
than replacing it: an installation that has never opened the console
keeps working exactly as before, and one that has keeps working if the
row is deleted. A setting that only works after somebody fills in a form
is a setting that takes an installation down the first time it is
deployed fresh.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class MailSecurity(StrEnum):
    """How the connection to the relay is protected.

    Three values rather than a pair of booleans. ``use_tls`` and
    ``start_tls`` as separate flags admits a combination that means
    nothing (both true) and one that silently sends credentials in clear
    (both false) — and the second is indistinguishable from a
    deliberate choice when it is two checkboxes.
    """

    #: Implicit TLS from the first byte. Conventionally port 465.
    TLS = "tls"
    #: Plain connection upgraded with STARTTLS. Conventionally port 587,
    #: and what most providers expect today.
    STARTTLS = "starttls"
    #: No transport security. Legitimate only for a relay on localhost
    #: or a trusted private network.
    NONE = "none"


@dataclass(frozen=True, slots=True)
class MailConfig:
    """Everything needed to send a message."""

    host: str
    port: int
    security: MailSecurity
    from_address: str
    from_name: str
    username: str | None = None
    password: str | None = None
    #: Seconds. Short by design: a mail relay that has not answered in
    #: fifteen seconds is not going to, and a worker blocked on a dead
    #: relay stops dispatching everything behind it.
    timeout_seconds: int = 15

    def redacted(self) -> "MailConfig":
        """The same configuration with the password removed.

        Used on every read path. The password is write-only from the
        API's point of view — an operator who can read it back has a way
        to exfiltrate a credential through a screen, and there is no
        legitimate reason to need it after it is set.
        """
        return replace(self, password=None)

    @property
    def requires_credentials(self) -> bool:
        return self.username is not None


def from_stored(stored: dict[str, Any] | None, *, defaults: MailConfig) -> MailConfig:
    """Layers a stored configuration over the environment defaults.

    Absent keys fall through to the default rather than being treated as
    empty, so a stored row written before a field existed does not blank
    that field out on the next read.

    A stored ``password`` of ``None`` means "unchanged", not "cleared" —
    the API never sends the password back, so a round-trip of the form
    would otherwise erase it. Clearing is done by sending an empty
    string, which is unambiguous.
    """
    if not stored:
        return defaults

    security = stored.get("security")
    return MailConfig(
        host=str(stored.get("host") or defaults.host),
        port=int(stored.get("port") or defaults.port),
        security=(
            MailSecurity(security) if security in set(MailSecurity) else defaults.security
        ),
        from_address=str(stored.get("from_address") or defaults.from_address),
        from_name=str(stored.get("from_name") or defaults.from_name),
        username=_optional(stored, "username", defaults.username),
        password=_optional(stored, "password", defaults.password),
        timeout_seconds=int(stored.get("timeout_seconds") or defaults.timeout_seconds),
    )


def _optional(stored: dict[str, Any], key: str, fallback: str | None) -> str | None:
    if key not in stored:
        return fallback
    value = stored[key]
    if value is None:
        return fallback
    text = str(value)
    # An explicit empty string is how the console says "remove this",
    # distinct from omitting the key, which says "leave it alone".
    return text or None


#: The conventional port for each mode, offered by the console so an
#: operator picking STARTTLS does not have to remember 587. A hint, not
#: a constraint: a relay on a non-standard port is perfectly normal.
DEFAULT_PORTS: dict[MailSecurity, int] = {
    MailSecurity.TLS: 465,
    MailSecurity.STARTTLS: 587,
    MailSecurity.NONE: 25,
}


__all__ = [
    "DEFAULT_PORTS",
    "MailConfig",
    "MailSecurity",
    "from_stored",
]
