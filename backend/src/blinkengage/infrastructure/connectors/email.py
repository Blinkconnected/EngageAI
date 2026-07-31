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

**Diagnostics ask the mailbox, and nothing else.** ``diagnose`` opens the same
SMTP session the send path opens and reports what that session proved:
whether the stored mailbox configuration is accepted, and whether the server
speaks ESMTP at all. It answers the inbound question too, because on this
channel the honest answer to "is the provider pointed at us?" is "nothing is
— we poll", and a support engineer left with an unanswered webhook row goes
hunting for a registration that was never meant to exist. Everything else on
the panel is something email cannot measure: there are no scopes on SMTP, no
rate-limit headroom in a greeting, and one probe's latency is not an average.
Those stay unanswered, which the platform renders as ``UNKNOWN`` — the true
statement, where a green tick would be a fabricated one.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import aiosmtplib

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    DeploymentContext,
)
from blinkengage.domain.connector_diagnostics import (
    Diagnostic,
    DiagnosticKey,
    DiagnosticReport,
    DiagnosticStatus,
)
from blinkengage.domain.connector_lifecycle import (
    ChannelFeature,
    Direction,
    FeatureSupport,
    Maturity,
    VersionInfo,
)
from blinkengage.domain.connector_manifest import (
    AuthMethod,
    ConnectorCategory,
    ConnectorManifest,
    CredentialSpec,
    ValidationCode,
    ValidationResult,
    VerificationSpec,
)
from blinkengage.domain.connectors import (
    Capability,
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

#: The qualifications on the feature matrix. Each one exists because the
#: unqualified row would be read as a promise this channel cannot keep — a
#: tick against Media that says nothing about where the bytes travel, or one
#: against Threading that a reader would take for a quoted reply bubble.
_FEATURE_INBOUND_NEEDS_IMAP = "connect.email.feature.inboundRequiresImapSettings"
_FEATURE_MEDIA_INSIDE_THE_MESSAGE = "connect.email.feature.mediaTravelsInsideTheMessage"
_FEATURE_THREADING_IS_INVISIBLE = "connect.email.feature.threadingByHeadersNotQuotes"

#: What ``diagnose`` found, as codes. Separate from the ``_FIX_*`` keys above
#: even where the finding rhymes: those are instructions written for a
#: customer part-way through a wizard, these are read by a support engineer
#: looking at a channel that has been live for a month, and copy that tries
#: to serve both audiences ends up addressing neither.
_DIAG_SMTP_HOST_MISSING = "connect.email.diagnostic.smtpHostMissing"
_DIAG_SMTP_UNREACHABLE = "connect.email.diagnostic.smtpUnreachable"
_DIAG_SMTP_REJECTED = "connect.email.diagnostic.smtpCredentialsRejected"
_DIAG_SMTP_ACCEPTED = "connect.email.diagnostic.smtpCredentialsAccepted"
_DIAG_SMTP_UNAUTHENTICATED = "connect.email.diagnostic.smtpRelayAcceptsUsUnauthenticated"
_DIAG_SERVER_SPEAKS_ESMTP = "connect.email.diagnostic.serverSpeaksEsmtp"
_DIAG_SERVER_WITHOUT_ESMTP = "connect.email.diagnostic.serverWithoutEsmtpNoAuthNoStartTls"
_DIAG_INBOUND_INCOMPLETE = "connect.email.diagnostic.inboundIncomplete"
_DIAG_INBOUND_BY_IMAP_POLL = "connect.email.diagnostic.noWebhookInboundByImapPoll"
_DIAG_INBOUND_SEND_ONLY = "connect.email.diagnostic.noWebhookAndNoImapSendOnly"

#: The form, and — because every stored key comes from it — the whitelist of
#: what may be written into an encrypted credentials blob. One list rather
#: than two so the two cannot drift apart, which is the failure where a
#: field is added to the form and then silently discarded on connect.
_CREDENTIAL_FIELDS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        name="smtp_host",
        kind="text",
        label_key="connect.email.smtpHostLabel",
        help_key="connect.email.smtpHostHelp",
        placeholder="smtp.example.com",
    ),
    CredentialSpec(
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
    CredentialSpec(
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
    CredentialSpec(
        name="smtp_password",
        kind="secret",
        label_key="connect.email.smtpPasswordLabel",
        help_key="connect.email.smtpPasswordHelp",
        required=False,
    ),
    CredentialSpec(
        name="smtp_use_tls",
        kind="boolean",
        label_key="connect.email.smtpUseTlsLabel",
        # The copy behind this key has to state the pairing, because the
        # setting is meaningless on its own: on for 465, off for 587, where
        # the connection starts in the clear and is upgraded.
        help_key="connect.email.smtpUseTlsHelpPairWithPort",
        required=False,
    ),
    CredentialSpec(
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
    CredentialSpec(
        name="imap_host",
        kind="text",
        label_key="connect.email.imapHostLabel",
        help_key="connect.email.imapHostHelpSendOnlyWithoutIt",
        placeholder="imap.example.com",
        required=False,
    ),
    CredentialSpec(
        name="imap_port",
        kind="number",
        label_key="connect.email.imapPortLabel",
        help_key="connect.email.imapPortHelp",
        placeholder=str(_DEFAULT_IMAP_PORT),
        required=False,
    ),
    CredentialSpec(
        name="imap_username",
        kind="text",
        label_key="connect.email.imapUsernameLabel",
        help_key="connect.email.imapUsernameHelpSendOnlyWithoutIt",
        required=False,
    ),
    CredentialSpec(
        name="imap_password",
        kind="secret",
        label_key="connect.email.imapPasswordLabel",
        help_key="connect.email.imapPasswordHelpSendOnlyWithoutIt",
        required=False,
    ),
    CredentialSpec(
        name="imap_use_ssl",
        kind="boolean",
        label_key="connect.email.imapUseSslLabel",
        help_key="connect.email.imapUseSslHelp",
        required=False,
    ),
    CredentialSpec(
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


def _inbound_outcome(credentials: dict[str, Any]) -> ValidationResult:
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
        return ValidationResult(
            ValidationCode.ADVISORY,
            channel_type="email",
            params={"check": _CHECK_SEND_ONLY},
            instructions_key=_FIX_ADD_IMAP_SETTINGS,
        )
    return ValidationResult(
        ValidationCode.OK, channel_type="email", params={"host": str(imap_host)}
    )


async def _probe_smtp(credentials: dict[str, Any]) -> tuple[ValidationResult, ...]:
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
                return (ValidationResult(ValidationCode.OK, channel_type="email", params=params),)
            try:
                await client.login(username, password)
            except Exception as exc:
                return (
                    ValidationResult(ValidationCode.OK, channel_type="email", params=params),
                    ValidationResult(
                        # The credential was rejected, which is what
                        # INVALID_TOKEN means whatever shape the credential
                        # takes — a bearer token here is a password.
                        ValidationCode.INVALID_TOKEN,
                        channel_type="email",
                        params=_with_detail(params, exc, credentials),
                        instructions_key=_FIX_SMTP_CREDENTIALS,
                    ),
                )
    except Exception as exc:
        # Deliberately broad, and never re-raised: a check that raised would
        # replace a list of findings with whichever one was evaluated first,
        # and half of what can go wrong at this layer — an unparseable port,
        # a hostname with a stray newline — is not an SMTP error at all.
        outcomes = [
            ValidationResult(
                ValidationCode.PROVIDER_UNREACHABLE,
                channel_type="email",
                params=_with_detail(params, exc, credentials),
                instructions_key=_FIX_SMTP_UNREACHABLE,
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
                ValidationResult(
                    ValidationCode.ADVISORY,
                    channel_type="email",
                    params={**params, "check": _CHECK_TLS_PORT_MISMATCH},
                    instructions_key=_FIX_TLS_PORT_PAIRING,
                )
            )
        return tuple(outcomes)

    return (
        ValidationResult(ValidationCode.OK, channel_type="email", params=params),
    )


def _esmtp_diagnostic(*, esmtp: bool, params: dict[str, str]) -> Diagnostic:
    """Which protocol the far side actually answered with.

    Measured, not declared. ``versions.api`` says what this connector speaks;
    this row says what the *server* speaks, and the two differ on exactly the
    machines where it matters. A relay that answers HELO and not EHLO has no
    ``AUTH`` and no ``STARTTLS`` to offer, which means a rejected login on
    port 587 is not a wrong password and no number of new app passwords will
    fix it — and it also means the mail is leaving this building in the
    clear, which is a sentence that ends differently in a hospital than it
    does in a startup. Worth a warning on its own for that reason, not only
    as an explanation for a failure beside it.
    """
    if esmtp:
        return Diagnostic(
            key=DiagnosticKey.API_VERSION,
            status=DiagnosticStatus.OK,
            value="esmtp",
            detail_key=_DIAG_SERVER_SPEAKS_ESMTP,
            params=params,
        )
    return Diagnostic(
        key=DiagnosticKey.API_VERSION,
        status=DiagnosticStatus.WARN,
        value="smtp",
        detail_key=_DIAG_SERVER_WITHOUT_ESMTP,
        params=params,
    )


async def _diagnose_smtp(credentials: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Open the session the send path opens, and report what it proved.

    ``AUTHENTICATION`` asks whether the stored credential still works, and on
    this channel the stored credential is the whole mailbox — host, port, TLS
    pairing, username, password. So a refused connection answers it as
    honestly as a refused password does: this configuration does not
    currently get mail out. The two are told apart by ``detail_key`` rather
    than by status, because they need the same urgency and different people:
    one is a firewall or a port, the other is an app password somebody has to
    regenerate.

    Never raises, and never guesses. Anything this probe did not establish is
    left off the report entirely for ``complete()`` to render as ``UNKNOWN``.
    """
    host = str(credentials.get("smtp_host") or "")
    raw_port = credentials.get("smtp_port", _DEFAULT_SMTP_PORT)
    # Coerced exactly as ``EmailProvider`` coerces it, for the same reason
    # ``_probe_smtp`` does: a diagnosis that read these values more sensibly
    # than the code that actually sends the mail would report a healthy
    # channel that cannot send.
    use_tls = bool(credentials.get("smtp_use_tls", True))
    username = str(credentials.get("smtp_username") or "")
    password = str(credentials.get("smtp_password") or "")
    params: dict[str, str] = {"host": host, "port": str(raw_port), "tls": str(use_tls).lower()}

    if not host:
        # A guard, not pedantry. ``aiosmtplib`` resolves an empty hostname to
        # the local machine, so probing without one would open a session to
        # whatever MTA happens to be listening beside this process and report
        # a green ``AUTHENTICATION`` for a mailbox that has no server at all
        # — a fabricated OK, arrived at by accident, on the one panel whose
        # entire value is that its green means something.
        return (
            Diagnostic(
                key=DiagnosticKey.AUTHENTICATION,
                status=DiagnosticStatus.FAIL,
                detail_key=_DIAG_SMTP_HOST_MISSING,
                params=params,
            ),
        )

    try:
        # aiosmtplib rather than ``httpx``: there is no HTTP anywhere in this
        # channel, and an HTTP client imported to satisfy a convention would
        # be a dependency that never opens a socket. The convention it is
        # actually there for — a probe that cannot hang a support engineer's
        # panel — is honoured by passing the same explicit timeout.
        async with aiosmtplib.SMTP(
            hostname=host,
            port=int(raw_port),
            use_tls=use_tls,
            timeout=_PROBE_TIMEOUT_SECONDS,
        ) as client:
            await client.noop()
            # Read here, inside the session: closing resets the client's
            # record of the greeting, so a version read afterwards would
            # always say the server speaks nothing.
            protocol = _esmtp_diagnostic(
                esmtp=client.last_ehlo_response is not None, params=params
            )
            if not username:
                # An unauthenticated relay has no password to verify, and the
                # row must not imply one was. OK is still the honest status —
                # the stored credential for this mailbox is "none", and the
                # server accepted us with it — but the detail says which
                # question was answered, so nobody reads the tick as proof of
                # a password that does not exist.
                return (
                    Diagnostic(
                        key=DiagnosticKey.AUTHENTICATION,
                        status=DiagnosticStatus.OK,
                        detail_key=_DIAG_SMTP_UNAUTHENTICATED,
                        params=params,
                    ),
                    protocol,
                )
            try:
                await client.login(username, password)
            except Exception as exc:
                return (
                    Diagnostic(
                        key=DiagnosticKey.AUTHENTICATION,
                        status=DiagnosticStatus.FAIL,
                        detail_key=_DIAG_SMTP_REJECTED,
                        params=_with_detail(params, exc, credentials),
                    ),
                    protocol,
                )
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.OK,
                    detail_key=_DIAG_SMTP_ACCEPTED,
                    params=params,
                ),
                protocol,
            )
    except Exception as exc:
        # Deliberately broad and never re-raised, for the reason the contract
        # gives: a diagnostics panel that 500s tells a support engineer
        # nothing at the moment they most need it. No protocol row here — the
        # session never opened, so nothing was learned about what the server
        # speaks, and inventing a value would be the fabrication this method
        # exists to avoid.
        return (
            Diagnostic(
                key=DiagnosticKey.AUTHENTICATION,
                status=DiagnosticStatus.FAIL,
                detail_key=_DIAG_SMTP_UNREACHABLE,
                params=_with_detail(params, exc, credentials),
            ),
        )


def _inbound_diagnostic(credentials: dict[str, Any]) -> Diagnostic:
    """``WEBHOOK_STATUS``, answered by a channel that has no webhook.

    Reported rather than omitted, and the reasoning is the whole argument for
    a closed key set. ``complete()`` renders an unanswered key as ``UNKNOWN``,
    so omitting this leaves a support engineer looking at "Webhook status:
    unknown" on an email channel — which sends them to look for a
    registration that was never meant to exist, and leaves the question they
    actually have ("is anything arriving?") unanswered on the one panel built
    to answer it. The key asks whether the provider is pointed at us. On this
    channel the true answer is that nothing is, because we poll; that answer
    fits in a ``detail_key``, and the status can then carry the part that
    varies.

    Which is why a configured mailbox is ``OK`` and not a standing warning
    about the missing webhook. This connector already argues, in
    ``_inbound_outcome``, that a warning firing on something that
    demonstrably works is how a checklist teaches people to stop reading it —
    and a permanent amber row on every correctly configured email channel is
    that mistake made once per page load.

    ``OK`` here claims exactly one thing: inbound is wired up, to this
    mailbox, and a scheduled poll collects it. It does not claim the IMAP
    password still works. Nothing is probed here — that credential is proven
    by ``EmailProvider.health_check``, whose verdict reaches the same panel
    through the platform's half of the report — so the detail key says
    "configured" and not "verified", which is the difference between a
    measurement and a fabrication.
    """
    imap_host = str(credentials.get("imap_host") or "")
    if not imap_host:
        # WARN, not FAIL. A send-only mailbox is a legitimate configuration —
        # statements, reminders, notifications — so nothing here is broken.
        # But "the customer replied and nobody saw it" is the single failure
        # this channel produces most, and it is invisible everywhere else on
        # the panel: outbound is green, health is green, and the reply is in
        # a mailbox nothing reads.
        return Diagnostic(
            key=DiagnosticKey.WEBHOOK_STATUS,
            status=DiagnosticStatus.WARN,
            detail_key=_DIAG_INBOUND_SEND_ONLY,
        )
    # UNKNOWN, not OK. A host being *configured* is not a mailbox being
    # *readable*, and this is the one row a support engineer reads as "is
    # anything arriving?". `email_imap_poll_task` needs a host, a username and
    # a password; a channel with a host and a wrong password would show green
    # here while nothing arrives — a fabricated green on the exact question
    # being asked, which is what makes a panel worse than no panel.
    #
    # Nothing else covers it either: the platform's half of the report
    # contributes health and log history, never WEBHOOK_STATUS, and the
    # connector wins the merge regardless. So the honest answer is that the
    # poll has not been observed, with what was configured shown beside it.
    incomplete = not credentials.get("imap_username") or not credentials.get(
        "imap_password"
    )
    return Diagnostic(
        key=DiagnosticKey.WEBHOOK_STATUS,
        status=DiagnosticStatus.WARN if incomplete else DiagnosticStatus.UNKNOWN,
        value=imap_host,
        detail_key=(
            _DIAG_INBOUND_INCOMPLETE if incomplete else _DIAG_INBOUND_BY_IMAP_POLL
        ),
        # The folder matters and is easy to get wrong: a poll pointed at a
        # folder the customer's own rules move mail out of finds nothing
        # while every other row stays green.
        params={"folder": str(credentials.get("imap_folder") or "INBOX")},
    )


@ConnectorRegistry.register("email")
class EmailConnector(Connector):
    channel_type = "email"
    #: No ``app_key``: there is no provider application to hold, which is
    #: also why nothing here degrades on a self-hosted installation. Email
    #: connects identically whether or not the operator has ever registered
    #: anything with anyone.
    MANIFEST = ConnectorManifest(
        channel_type="email",
        name_key="connect.email.name",
        description_key="connect.email.description",
        category=ConnectorCategory.EMAIL,
        icon="email",
        capabilities=frozenset(
            {Capability.MANUAL_CONFIGURATION, Capability.HEALTH_CHECKS}
        ),
        auth_methods=(AuthMethod.CREDENTIALS,),
        required_credentials=_CREDENTIAL_FIELDS,
        verification_steps=(
            VerificationSpec(
                key="connect.email.check.smtp",
                title_key="connect.email.check.smtp.title",
                codes=(
                    ValidationCode.OK,
                    ValidationCode.MISSING_CREDENTIAL,
                    ValidationCode.INVALID_TOKEN,
                    ValidationCode.PROVIDER_UNREACHABLE,
                ),
            ),
            VerificationSpec(
                key="connect.email.check.inbound",
                title_key="connect.email.check.inbound.title",
                # A send-only mailbox is a legitimate configuration, not a
                # fault — so the worst this step reports is advice.
                codes=(ValidationCode.OK, ValidationCode.ADVISORY),
            ),
        ),
        # Deliberately no webhook capability and so no webhook repair:
        # inbound email is polled over IMAP, and declaring webhooks would
        # promise a callback that never arrives.
        #
        # Four rows, and the absences below them are the load-bearing part.
        # Every one of these is read off ``EmailProvider``: what it sends,
        # what it parses, and — for most of the enum — which of its methods
        # accept a call and then do nothing.
        supported_features=(
            # ``send_message`` builds a MIME message and hands it to
            # ``aiosmtplib.send``. Outbound only, and not because of a
            # limitation: "send" and "receive" are separate rows here, and a
            # channel that does both says so twice rather than once
            # ambiguously.
            FeatureSupport(ChannelFeature.SEND_MESSAGES, Direction.OUTBOUND),
            # ``receive_message`` parses raw MIME into an ``InboundMessage``,
            # and either the IMAP poll or a raw-MIME POST from an ESP feeds
            # it. The note carries the condition that a static matrix cannot:
            # this connector *can* receive, but a channel saved without IMAP
            # settings and without an ESP arrangement receives nothing at all
            # — which is a property of one installation's configuration, so
            # it is qualified here and measured per channel in ``diagnose``.
            FeatureSupport(
                ChannelFeature.RECEIVE_MESSAGES,
                Direction.INBOUND,
                note_key=_FEATURE_INBOUND_NEEDS_IMAP,
            ),
            # Both directions, genuinely. Outbound, ``send_message`` downloads
            # each attachment and calls ``add_attachment``; inbound,
            # ``receive_message`` walks the MIME parts, uploads anything with
            # an attachment disposition and returns an ``AttachmentRef`` for
            # it. Qualified because email carries the bytes *inside* the
            # message rather than behind a link, so the ceiling is whatever
            # the receiving server accepts — a limit nothing in this product
            # sets, sees, or can report, and one that rejects the message
            # rather than trimming it.
            FeatureSupport(
                ChannelFeature.MEDIA,
                Direction.BOTH,
                note_key=_FEATURE_MEDIA_INSIDE_THE_MESSAGE,
            ),
            # The one row this connector is alone in claiming, and the one
            # most in need of its note. ``EmailProvider`` is the only provider
            # with ``supports_invisible_reply_threading``: outbound it sets
            # ``In-Reply-To`` and ``References`` from
            # ``reply_to_external_message_id``, inbound it reads them back
            # into ``external_thread_id`` and ``reply_to_external_message_id``
            # — a real correlation to a specific earlier message, in both
            # directions. But ``ChannelFeature.THREADING`` is documented as
            # replying to an earlier message *visibly*, and this is the exact
            # opposite: the headers are invisible to the reader, and what they
            # see is their mail client's own grouping, if it groups at all.
            # Dropping the row would deny threading that demonstrably works;
            # taking it unqualified would promise the quoted-reply bubble
            # WhatsApp and Telegram draw. The note is the only honest third
            # option.
            FeatureSupport(
                ChannelFeature.THREADING,
                Direction.BOTH,
                note_key=_FEATURE_THREADING_IS_INVISIBLE,
            ),
            # Absent, each for a reason found in ``EmailProvider`` rather than
            # assumed about email: ``edit_message`` returns the id back
            # unchanged and ``delete_message`` returns ``None`` — both are
            # stubs satisfying the interface, so EDIT_MESSAGES and
            # DELETE_MESSAGES would be buttons that appear to work and change
            # nothing on the far side, which is worse than their absence.
            # ``mark_as_read`` and ``typing_indicator`` are the same shape of
            # no-op, and there is nothing they could call: SMTP has no live
            # signal and read receipts (RFC 3798) are a request the recipient
            # may ignore, not a fact we could report. No REACTIONS, TEMPLATES,
            # BROADCASTS, INTERACTIVE_MESSAGES, VOICE_CALLS or VIDEO_CALLS:
            # nothing in this connector or its provider implements any of
            # them, and a matrix that ticked them from what the *medium* could
            # theoretically do would be describing a product we have not
            # written.
        ),
        # BETA, and the distance from both neighbours is deliberate.
        #
        # Not PREVIEW: every path a customer can take is implemented end to
        # end and none of it is waiting on anybody. There is no OAuth to be
        # unimplemented, no provider application an operator must register
        # first, and no method here that raises ``NotImplementedError`` — this
        # connector behaves identically on a hosted installation and on one
        # air-gapped in a bank, because it asks nothing of a third party.
        # ``validate`` really opens SMTP, ``connect`` really writes a usable
        # mailbox, ``EmailProvider`` really sends and parses, and the IMAP
        # poll is scheduled and running.
        #
        # Not PRODUCTION: that word promises backwards-compatible change, and
        # nothing here has yet met a customer's mail server. The two things
        # most likely to move are known and both are contracts other code
        # already depends on — the shape of the stored credential blob, whose
        # IMAP half is read by a separate Celery task, and inbound MIME
        # parsing, which today takes the first ``text/plain`` part and so
        # returns an empty body for the HTML-only mail some senders produce.
        # Fixing either after promising compatibility would be a migration;
        # fixing them in beta is a fix. Feature-complete and being proven is
        # exactly what this is.
        maturity=Maturity.BETA,
        versions=VersionInfo(
            connector="1.0.0",
            # No vendor API to name, so this states the two wire contracts the
            # code actually speaks, read off the code that speaks them.
            # Outbound is ``aiosmtplib`` doing ESMTP submission on 587 or 465.
            # Inbound is ``imaplib`` — in ``EmailProvider._check_imap`` and in
            # ``email_imap_poll_task``, whose SELECT / SEARCH UNSEEN / FETCH
            # (RFC822) / STORE +FLAGS vocabulary is IMAP4rev1. Claiming
            # IMAP4rev2 would be claiming a contract this code does not
            # speak: RFC 9051 retired the ``RFC822`` fetch item this poll is
            # built on.
            api="SMTP (RFC 5321) + IMAP4rev1 (RFC 3501)",
            minimum_platform="1.0.0",
        ),
    )

    @property
    def manifest(self) -> ConnectorManifest:
        return self.MANIFEST

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
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

    async def diagnose(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> DiagnosticReport:
        """What this mailbox can be asked, and only that.

        Three rows, from two questions worth asking a live email channel:
        does it still get mail out (``AUTHENTICATION``, and ``API_VERSION``
        for what the server answered with), and is anything coming back in
        (``WEBHOOK_STATUS``). Both are things only this connector can find
        out, which is the division the report is merged along.

        Everything else is deliberately absent rather than filled in, and the
        absences are the honest half of the contract:

        - ``PERMISSIONS`` — SMTP has no scopes. A mailbox can send or it
          cannot, and that is the ``AUTHENTICATION`` row already.
        - ``RATE_LIMITS`` — mail servers throttle, sometimes brutally, and
          none of them publish headroom. There is no header to read and no
          counter to query, so any number here would be invented.
        - ``AVERAGE_RESPONSE_TIME`` — this probe knows how long *it* took.
          One sample is not an average, and presenting it as one would put a
          statistic in front of a support engineer that changes every time
          they press refresh.
        - ``LAST_SUCCESSFUL_SYNC``, ``LAST_FAILED_REQUEST``, ``RETRY_QUEUE``
          — the platform's own knowledge, from stored state it keeps for
          every channel. ``merge`` gives the connector's answer priority, so
          a connector answering these would overwrite a real history with a
          single live probe.
        - ``CONNECTION_HEALTH`` — the badge, derived from everything above by
          ``DiagnosticReport.worst``. A connector asserting it would be
          voting on a result it can only see part of.

        ``context`` is unused: this channel has no provider application, no
        callback URL to build and nothing that varies per installation, which
        is the same reason the connector has no ``app_key``.
        """
        return DiagnosticReport(
            channel_type=self.channel_type,
            items=(*await _diagnose_smtp(credentials), _inbound_diagnostic(credentials)),
        )

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
