"""``EmailConnector`` — the channel with nobody on the other side.

Every other connector in this package negotiates with a company. Meta holds
the app, issues the token, hands back a list of Pages and delivers the
webhook; the capability set falls out of what that company is willing to do
for us. Email has no such counterparty. A mailbox is a hostname, a port and
a password handed over by whoever runs the customer's mail server — Google,
an Exchange cluster in a hospital basement, or a relay on the same VLAN that
accepts anything from this host without asking who it is. That absence is
what decides every capability below, and it is why this file is short.

**Manual configuration, with nothing standing in for it.** There is no OAuth
because there is no authorization server: SMTP has no consent screen and
never will. Gmail and Microsoft 365 do offer OAuth for mail, and when that
is worth having it belongs in its own connector with its own ``app_key`` —
"connect your Google Workspace" is a different flow with different scopes, a
different review process and a different set of ways to fail than "connect
an SMTP server", and folding the two together would make one form
conditionally mean two things, which is how a wizard starts branching on
things it should not know. So manual configuration is not the fallback path
here the way it is for Meta. It is the whole path.

**Nothing to discover.** ``AUTO_DISCOVERY`` promises the customer a list of
what they own, and no query returns one: the mailbox has to be named before
a connection can be opened at all, so by the time we could ask, the answer
is already on the form. IMAP will happily enumerate folders, but a folder is
a setting here, not a resource to choose between — offering a picker whose
single row is a value the customer typed one step earlier is a step that
exists to be clicked past.

**No webhooks, and this is the deliberate one.** Inbound mail is polled over
IMAP by ``infrastructure/tasks/email_imap_poll_task.py``. ``EmailProvider``
does implement ``webhook()``, and an ESP configured to POST raw MIME at the
generic ``/webhooks/{channel_config_id}`` route will be parsed correctly —
but that is an arrangement the operator makes inside their ESP's dashboard,
out of band, with no involvement from this flow. Nothing here registers that
callback, nothing here signs it, and no ``webhook_secret`` this connector
invented would ever be checked against it. ``register_webhook`` is left at
the base class's refusal for the same reason: the hook exists so a connector
whose callback URL contains the channel's id can register it once the row
has been written and the id is real, and there is no counterparty here to
tell. Declaring the capability would have the wizard tell a customer that
inbound is taken care of, when what is actually taken care of depends
entirely on work the wizard never mentioned. ``Capability.WEBHOOKS`` says it
plainly: absent for a connector we poll.

**No token refresh.** A password has no expiry we can see and no renewal we
could perform unattended. When a provider revokes an app password the fix is
a human generating another one, which is a repair, not a refresh — treating
it as refreshable would turn "your mailbox is disconnected, go make a new
password" into a button that cannot work.

**Health checks, because SMTP is cheap to ask.** Open a connection, NOOP,
and log in if credentials were supplied: no message is sent, nothing is
billed, and it is the same probe ``EmailProvider.health_check`` already runs
on a timer, which is the bar ``Capability.HEALTH_CHECKS`` sets.

The optional IMAP half is the genuinely awkward part of this channel, and
the reason ``check`` reports a warning rather than a failure. A send-only
mailbox is a legitimate configuration — outbound notifications, statements,
appointment reminders — so failing it would refuse a channel that works
exactly as intended. But saying nothing would hand somebody a channel that
goes green and then silently swallows every reply their customer sends,
which is the worst outcome available. A warning is the only honest position
between the two: the flow continues, and the customer has been told once, in
the one place they are certainly looking. It carries ``FIX_REENTER``,
because the remedy is six more fields on the form they were looking at one
step ago — a move inside our own wizard, not a trip to somebody's dashboard
and not a consent screen this channel does not have.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import aiosmtplib

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    Field,
)
from blinkengage.domain.connectors import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    FIX_MANUAL,
    FIX_REENTER,
    Capability,
    CheckOutcome,
    Fix,
)
from blinkengage.infrastructure.channels.error_sanitizer import redact_credentials
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: Mirrors the fallbacks in ``EmailProvider`` and ``email_imap_poll_task``,
#: so a value omitted here means at connect time exactly what it will mean
#: at send time.
_DEFAULT_SMTP_PORT = 587
_DEFAULT_IMAP_PORT = 993

#: The two ports whose meaning is fixed by convention rather than by
#: configuration: 465 is TLS from the first byte, 587 expects a plaintext
#: greeting and an upgrade. Mixing them up is the single most common way an
#: otherwise correct mailbox fails to send, and it fails at connect time
#: with a message about handshakes that tells the customer nothing.
_IMPLICIT_TLS_PORT = 465
_SUBMISSION_PORT = 587

#: Long enough for a TLS handshake to a slow corporate relay, short enough
#: that a customer watching the checklist does not conclude it has hung. The
#: periodic sweep in ``EmailProvider`` can afford to be stricter; a person
#: waiting cannot afford to be strung along.
_PROBE_TIMEOUT_SECONDS = 8.0

#: Server diagnostics are quoted back to the customer, so they are bounded.
#: A mail server that answers a failed login with a paragraph is not adding
#: information after the first line.
_MAX_DETAIL_CHARS = 200

_CHECK_SMTP_CONNECTION = "connect.email.check.smtpConnection"
_CHECK_SMTP_AUTHENTICATION = "connect.email.check.smtpAuthentication"
_CHECK_TLS_PORT_MISMATCH = "connect.email.check.tlsPortMismatch"
_CHECK_IMAP_CONFIGURED = "connect.email.check.imapConfigured"
_CHECK_SEND_ONLY = "connect.email.check.sendOnly"

_FIX_SMTP_UNREACHABLE = "connect.email.fix.smtpUnreachable"
_FIX_SMTP_CREDENTIALS = "connect.email.fix.smtpCredentials"
_FIX_TLS_PORT_PAIRING = "connect.email.fix.tlsPortPairing"
_FIX_ADD_IMAP_SETTINGS = "connect.email.fix.addImapSettings"

#: The form, and — because every stored key comes from it — the whitelist of
#: what may be written into an encrypted credentials blob. One list rather
#: than two so the two cannot drift apart, which is the failure where a
#: field is added to the form and then silently discarded on connect.
_CREDENTIAL_FIELDS: tuple[Field, ...] = (
    Field(
        name="smtp_host",
        kind="text",
        label_key="connect.email.smtpHostLabel",
        help_key="connect.email.smtpHostHelp",
        placeholder="smtp.example.com",
    ),
    Field(
        # Required here even though ``EmailCredentials`` tolerates its
        # absence. The provider's own fallbacks are port 587 with implicit
        # TLS — a pair almost no server accepts — so a blank port is not a
        # sensible default, it is a channel that saves cleanly and never
        # sends. Better to make the customer answer than to guess wrong.
        name="smtp_port",
        kind="number",
        label_key="connect.email.smtpPortLabel",
        help_key="connect.email.smtpPortHelp",
        placeholder=str(_DEFAULT_SMTP_PORT),
    ),
    Field(
        # Optional because unauthenticated internal relays are ordinary in
        # exactly the sectors this product sells into: an on-premise MTA
        # that accepts mail from a known host and asks for no password.
        # Requiring credentials would force those customers to invent some.
        name="smtp_username",
        kind="text",
        label_key="connect.email.smtpUsernameLabel",
        help_key="connect.email.smtpUsernameHelp",
        required=False,
    ),
    Field(
        name="smtp_password",
        kind="secret",
        label_key="connect.email.smtpPasswordLabel",
        help_key="connect.email.smtpPasswordHelp",
        required=False,
    ),
    Field(
        name="smtp_use_tls",
        kind="boolean",
        label_key="connect.email.smtpUseTlsLabel",
        # The copy behind this key has to state the pairing, because the
        # setting is meaningless on its own: on for 465, off for 587, where
        # the connection starts in the clear and is upgraded.
        help_key="connect.email.smtpUseTlsHelpPairWithPort",
        required=False,
    ),
    Field(
        # Required, unlike in the schema. The provider falls back to the
        # SMTP username for the From header, and the username is optional
        # here — leaving both empty produces mail with no sender, which
        # every receiving server treats as spam. It is also the address the
        # customer's own customers will reply to, so it is not a detail to
        # be inferred.
        name="from_address",
        kind="text",
        label_key="connect.email.fromAddressLabel",
        help_key="connect.email.fromAddressHelp",
        placeholder="support@example.com",
    ),
    Field(
        name="imap_host",
        kind="text",
        label_key="connect.email.imapHostLabel",
        help_key="connect.email.imapHostHelpSendOnlyWithoutIt",
        placeholder="imap.example.com",
        required=False,
    ),
    Field(
        name="imap_port",
        kind="number",
        label_key="connect.email.imapPortLabel",
        help_key="connect.email.imapPortHelp",
        placeholder=str(_DEFAULT_IMAP_PORT),
        required=False,
    ),
    Field(
        name="imap_username",
        kind="text",
        label_key="connect.email.imapUsernameLabel",
        help_key="connect.email.imapUsernameHelpSendOnlyWithoutIt",
        required=False,
    ),
    Field(
        name="imap_password",
        kind="secret",
        label_key="connect.email.imapPasswordLabel",
        help_key="connect.email.imapPasswordHelpSendOnlyWithoutIt",
        required=False,
    ),
    Field(
        name="imap_use_ssl",
        kind="boolean",
        label_key="connect.email.imapUseSslLabel",
        help_key="connect.email.imapUseSslHelp",
        required=False,
    ),
    Field(
        name="imap_folder",
        kind="text",
        label_key="connect.email.imapFolderLabel",
        help_key="connect.email.imapFolderHelp",
        placeholder="INBOX",
        required=False,
    ),
)


def _stored_credentials(submitted: dict[str, Any]) -> dict[str, Any]:
    """The submitted form, reduced to what belongs in the credentials blob.

    Blanks are dropped rather than stored, because a stored empty string is
    not the same as an absent key downstream: the provider reads its
    defaults with ``credentials.get(name, default)``, and ``int("")`` raises
    where a missing port would quietly have become 587. Unknown keys are
    dropped for the opposite reason — anything a console posts here is
    encrypted and kept, so the set of things it can persist is the set of
    things it was asked for.
    """
    return {
        field.name: submitted[field.name]
        for field in _CREDENTIAL_FIELDS
        if submitted.get(field.name) not in (None, "")
    }


def _with_detail(
    params: dict[str, str], exc: Exception, credentials: dict[str, Any]
) -> dict[str, str]:
    """Attach the server's own words, with the customer's secrets removed.

    A checklist line that says only "could not connect" sends the customer
    to their mail administrator with nothing; "certificate verify failed" and
    "name or service not known" are different problems with different owners.
    The text is the mail server's, not ours, so it is the one thing on this
    screen that is not a translation key — and because it is quoted verbatim
    it goes through the same redaction that keeps provider errors from
    turning stored diagnostics into a credential leak.
    """
    return {**params, "detail": redact_credentials(str(exc), credentials)[:_MAX_DETAIL_CHARS]}


def _tls_and_port_disagree(raw_port: Any, *, use_tls: bool) -> bool:
    return (int(raw_port) == _SUBMISSION_PORT and use_tls) or (
        int(raw_port) == _IMPLICIT_TLS_PORT and not use_tls
    )


def _inbound_outcome(credentials: dict[str, Any]) -> CheckOutcome:
    """Whether anything will ever arrive, and how sure we are.

    Two codes rather than one code at two levels: "we will poll this
    mailbox" and "this channel can only send" are not the same sentence with
    a different colour, and a console that had to derive one from the other
    would be deriving copy from a level. The configured case reports what
    was configured and not that it works — the credentials are not tried
    here, and the first health check is what proves them.
    """
    imap_host = credentials.get("imap_host")
    if not imap_host:
        # ``reenter`` and nothing else. ``action`` is a button this connector
        # would have to answer, and there is no call it could make; ``manual``
        # would point the customer at somebody else's dashboard for a form we
        # drew ourselves; ``reauthorize`` would render a consent button on a
        # channel with no authorization server behind it, which is the
        # mistake that kind was added to stop. What actually resolves this is
        # one step back and six more fields, and that is now sayable.
        return CheckOutcome(
            _CHECK_SEND_ONLY,
            CHECK_WARN,
            fix=Fix(FIX_REENTER, instructions_key=_FIX_ADD_IMAP_SETTINGS),
        )
    return CheckOutcome(_CHECK_IMAP_CONFIGURED, CHECK_OK, params={"host": str(imap_host)})


async def _probe_smtp(credentials: dict[str, Any]) -> tuple[CheckOutcome, ...]:
    """Open the connection the send path will open, and say what happened.

    Reachability and credentials are reported separately because they fail
    for unrelated reasons and are fixed by different people: a refused
    connection is usually a firewall or a wrong port, a rejected login is
    usually an app password that was never generated. Collapsing them into
    one line would make the customer test both to learn which one it was.
    """
    host = str(credentials.get("smtp_host", ""))
    raw_port = credentials.get("smtp_port", _DEFAULT_SMTP_PORT)
    # Coerced exactly as ``EmailProvider`` coerces it, quirks included —
    # ``bool("false")`` is ``True`` there and so it is here. A check that
    # read these values more sensibly than the code that will actually send
    # the mail would pass a channel that cannot send, which is the one
    # result a verification step must never produce.
    use_tls = bool(credentials.get("smtp_use_tls", True))
    username = str(credentials.get("smtp_username") or "")
    password = str(credentials.get("smtp_password") or "")
    params: dict[str, str] = {"host": host, "port": str(raw_port), "tls": str(use_tls).lower()}

    try:
        async with aiosmtplib.SMTP(
            hostname=host,
            port=int(raw_port),
            use_tls=use_tls,
            timeout=_PROBE_TIMEOUT_SECONDS,
        ) as client:
            await client.noop()
            if not username:
                # An unauthenticated relay has no login to report on, and a
                # green line saying so would imply a check that never ran.
                return (CheckOutcome(_CHECK_SMTP_CONNECTION, CHECK_OK, params=params),)
            try:
                await client.login(username, password)
            except Exception as exc:
                return (
                    CheckOutcome(_CHECK_SMTP_CONNECTION, CHECK_OK, params=params),
                    CheckOutcome(
                        _CHECK_SMTP_AUTHENTICATION,
                        CHECK_FAIL,
                        params=_with_detail(params, exc, credentials),
                        fix=Fix(FIX_MANUAL, instructions_key=_FIX_SMTP_CREDENTIALS),
                    ),
                )
    except Exception as exc:
        # Deliberately broad, and never re-raised: a check that raised would
        # replace a list of findings with whichever one was evaluated first,
        # and half of what can go wrong at this layer — an unparseable port,
        # a hostname with a stray newline — is not an SMTP error at all.
        outcomes = [
            CheckOutcome(
                _CHECK_SMTP_CONNECTION,
                CHECK_FAIL,
                params=_with_detail(params, exc, credentials),
                fix=Fix(FIX_MANUAL, instructions_key=_FIX_SMTP_UNREACHABLE),
            )
        ]
        try:
            mismatched = _tls_and_port_disagree(raw_port, use_tls=use_tls)
        except (TypeError, ValueError):
            mismatched = False
        if mismatched:
            # Only ever raised alongside a failure it explains. On its own
            # it would be a guess about a working configuration, and a
            # warning that fires on something that demonstrably works is how
            # a checklist teaches people to stop reading it.
            outcomes.append(
                CheckOutcome(
                    _CHECK_TLS_PORT_MISMATCH,
                    CHECK_WARN,
                    params=params,
                    fix=Fix(FIX_MANUAL, instructions_key=_FIX_TLS_PORT_PAIRING),
                )
            )
        return tuple(outcomes)

    return (
        CheckOutcome(_CHECK_SMTP_CONNECTION, CHECK_OK, params=params),
        CheckOutcome(_CHECK_SMTP_AUTHENTICATION, CHECK_OK, params=params),
    )


@ConnectorRegistry.register("email")
class EmailConnector(Connector):
    channel_type = "email"
    #: No ``app_key``: there is no provider application to hold, which is
    #: also why nothing here degrades on a self-hosted installation. Email
    #: connects identically whether or not the operator has ever registered
    #: anything with anyone.
    declares = frozenset({Capability.MANUAL_CONFIGURATION, Capability.HEALTH_CHECKS})

    def credential_fields(self) -> tuple[Field, ...]:
        return _CREDENTIAL_FIELDS

    async def check(self, attempt: Attempt) -> tuple[CheckOutcome, ...]:
        """Everything worth saying before this mailbox is written down.

        Read from ``inputs`` and never from ``grant`` or ``credentials``.
        There is no consent step on this channel, so ``grant`` is empty and
        ``credentials`` only ever falls through to the same dict — but the
        two would stop agreeing the moment a hosted-mailbox connector with an
        actual authorization server appears alongside this one, and probing
        SMTP against consent material is the way a check ends up silently
        testing an empty dict. The values are typed; ``inputs`` is where
        typed values live.
        """
        credentials = _stored_credentials(attempt.inputs)
        return (*await _probe_smtp(credentials), _inbound_outcome(credentials))

    async def connect(
        self, *, company_id: UUID, attempt: Attempt
    ) -> tuple[Connection, ...]:
        """Write down the mailbox, and nothing else.

        There is no subscription to create, no callback to register and no
        secret to invent — the inbound path is a poll this company's channel
        row already qualifies for. Leaving ``webhook_secret`` unset is the
        accurate statement of that: a random value here would be a signing
        key nothing signs with and nothing verifies, indistinguishable at a
        glance from a channel whose webhook security is actually configured.

        The mailbox address carries into ``external_id`` because it is the
        only identity email has on the far side. Nothing routes by it today
        — the IMAP poll finds its work by channel row — but it is what a
        delivered MIME message would have to be matched on, and it is the
        value an operator looking at two similar rows needs to tell them
        apart.

        The name the customer chose wins, and it now arrives in a field of
        its own rather than having to survive the credential whitelist —
        which it did not, so until this contract every email channel was
        named after its own mailbox no matter what the customer typed on the
        naming input. The mailbox remains the fallback, and the SMTP host the
        fallback after that: both are values the customer supplied, so
        neither is an English sentence stored in a column that is rendered
        verbatim into channel lists, reports and PDF exports.
        """
        stored = _stored_credentials(attempt.inputs)
        from_address = stored.get("from_address")
        mailbox = str(from_address) if from_address else None
        chosen_name = attempt.display_name.strip()
        return (
            Connection(
                channel_type=self.channel_type,
                display_name=chosen_name or mailbox or str(stored.get("smtp_host", "")),
                credentials=stored,
                external_id=mailbox,
            ),
        )


__all__ = ["EmailConnector"]
