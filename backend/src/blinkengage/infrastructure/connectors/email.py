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

**Certification proves four things and admits to the rest.** ``run_scenario``
executes what a mailbox can actually be made to demonstrate — authentication,
a send, a send carrying an attachment, and a read of the folder the inbound
poll reads — and returns ``SKIPPED`` for everything else rather than a pass
it did not earn. The two sends are real mail, to an address somebody typed on
purpose; that is why the runner withholds them without a target and why
nothing here guesses one.

What is deliberately *not* executed is the load-bearing half:

- ``MEDIA_DOWNLOAD`` would need an inbound message that happens to carry an
  attachment. There is no fixture to fetch — the only candidates are the
  customer's own mail, and reading it (and, with the poll's ``\\Seen`` flag,
  consuming it) to prove that we could is not a thing a certification run may
  do. Selecting the folder proves the transport, not the extraction, so a
  pass here would be certifying MIME walking that never ran.
- ``WEBHOOK_DELIVERY`` reaches this connector because the scenario has no
  feature behind it and so applies to everybody. It is not a failure: this
  connector declares no ``Capability.WEBHOOKS`` and the module docstring
  above says why. It is not ``NOT_SUPPORTED`` either, because that verdict
  belongs to the runner and a connector answering it would be editing its own
  denominator. It is ``SKIPPED``, with the reason.
- ``TOKEN_REFRESH``, ``DISCONNECT`` and ``RECONNECT`` reach this connector
  only when an operator asks for mutating scenarios by name. A password has
  no refresh, and a mailbox holds no session, subscription or registration on
  our behalf — there is nothing to tear down and nothing to re-establish that
  ``AUTHENTICATION`` has not already opened. Re-opening SMTP and calling it a
  reconnect would put the same measurement in the score twice under a second
  name, which is the quiet way a suite inflates itself.

The consequence is a coverage figure below the bar and an ``INCONCLUSIVE``
grade on a channel that demonstrably works, and that is the correct outcome:
this connector can be *shown* to authenticate, send and read, and the rest is
genuinely unanswered. Skipping is what "unanswered" is for. Fabricating five
passes to reach ``PRODUCTION_READY`` would be exactly the sentence the
certification module was written to make impossible.

**No ``supported_until``.** The base class returns ``None`` and this connector
leaves it there, which is the whole answer: SMTP and IMAP4rev1 are IETF
standards with no vendor and no retirement schedule, and there is nothing to
read one off. Individual mail providers *do* retire authentication mechanisms
on dates — Microsoft's basic-auth retirements are the obvious example — but
those are properties of one tenant's mail host, and this connector points at
whatever hostname the customer typed, which may be an Exchange cluster in a
hospital basement that nobody is retiring anything on. A date invented from
somebody else's schedule is worse than no date, because administrators plan
migrations around it.
"""

from __future__ import annotations

import base64
import contextlib
import imaplib
from dataclasses import dataclass, replace
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib
from anyio import to_thread

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    DeploymentContext,
)
from blinkengage.domain.connector_certification import (
    Outcome,
    ScenarioKind,
    ScenarioResult,
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

#: More than the probe above, because a certification scenario does more than
#: greet: it hands over a whole message, attachment included, and a relay that
#: scans mail inline can take seconds over it. Still comfortably inside the
#: runner's own per-scenario budget, so a slow mailbox is reported as slow
#: rather than as the reason a whole run was abandoned.
_SCENARIO_TIMEOUT_SECONDS = 15.0

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

#: What a certification run found, as codes, in the runner's own namespace —
#: ``certification.*`` is where ``certification.skipped.noTarget`` and
#: ``certification.raised`` already live, and a report whose rows came from
#: two namespaces would be one the console resolves in two places.
#:
#: The ``AUTHENTICATION`` row is the exception and deliberately reuses the
#: ``_DIAG_*`` keys above. That scenario *is* the diagnostics probe — same
#: function, same session, same verdict — so it says it in the same words. A
#: parallel set of keys would be a second sentence about one measurement, and
#: two sentences about one measurement are two sentences that can disagree.
_CERT_SEND_ACCEPTED = "certification.email.send.acceptedForDelivery"
_CERT_SEND_REJECTED = "certification.email.send.rejectedByTheServer"
_CERT_SEND_PARTIAL = "certification.email.send.someRecipientsRefused"
_CERT_SEND_NO_SENDER = "certification.email.send.noFromAddressToSendAs"
_CERT_SEND_MALFORMED = "certification.email.send.storedValuesDoNotMakeAValidMessage"
_CERT_MEDIA_ACCEPTED = "certification.email.media.attachmentAcceptedForDelivery"
_CERT_MEDIA_REJECTED = "certification.email.media.attachmentRejectedOftenASizeLimit"
_CERT_TARGET_NOT_AN_ADDRESS = "certification.email.skipped.targetIsNotAnEmailAddress"

_CERT_RECEIVE_READABLE = "certification.email.receive.mailboxReadableNoMessageFetched"
_CERT_RECEIVE_UNREACHABLE = "certification.email.receive.imapUnreachable"
_CERT_RECEIVE_LOGIN_REJECTED = "certification.email.receive.imapCredentialsRejected"
_CERT_RECEIVE_FOLDER_UNSELECTABLE = "certification.email.receive.polledFolderNotSelectable"
_CERT_RECEIVE_SEARCH_REFUSED = "certification.email.receive.mailboxRefusedSearch"
_CERT_RECEIVE_SEND_ONLY = "certification.email.skipped.sendOnlyMailboxNothingToRead"

_CERT_NOT_MEASURED = "certification.email.skipped.probeAnsweredNothing"
_CERT_NO_INBOUND_MEDIA = "certification.email.skipped.wouldHaveToReadCustomerMail"
_CERT_NO_WEBHOOK = "certification.email.skipped.noWebhookInboundIsPolled"
_CERT_NO_TOKEN = "certification.email.skipped.aPasswordHasNoRefresh"
_CERT_NO_SESSION = "certification.email.skipped.noProviderSessionToDropOrReopen"
_CERT_PROVIDER_NO_OP = "certification.email.skipped.providerMethodIsANoOp"

#: The certification mail itself. English, not a translation key, and the only
#: text in this file that is: a MIME body is rendered by the recipient's mail
#: client, which has never heard of our console and cannot resolve anything.
#: It says who sent it and why in the first sentence, because the person who
#: opens it may be a test-mailbox owner who was not told a run was happening.
_CERTIFICATION_SUBJECT = "Blink Engage connector certification"
_CERTIFICATION_BODY = (
    "This message was sent by a Blink Engage connector certification run, to "
    "prove that this mailbox can send mail.\n\n"
    "It went to this address because somebody entered it as the certification "
    "target. No action is required and nothing is waiting on a reply.\n\n"
    "Sent by: {origin}\n"
)

#: RFC 3834. Keeps a test send from waking somebody's vacation autoresponder,
#: and keeps this connector out of the mail loop that would start if the
#: target were an address that replies automatically.
_AUTO_SUBMITTED = "auto-generated"
#: Not a header anything of ours reads — it is here so that a person looking
#: at the raw message, days later, can tell a certification send from real
#: outbound mail without guessing from the subject line.
_CERTIFICATION_HEADER = "X-BlinkEngage-Certification"

#: A 1×1 transparent PNG: 70 bytes, and binary, which is the point. A text
#: attachment would travel as 7-bit and prove nothing about the base64 part
#: real customer attachments arrive as — this exercises the same MIME
#: construction ``EmailProvider.send_message`` builds for an actual file, at a
#: size no mail server has a limit small enough to refuse.
_CERTIFICATION_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)
_CERTIFICATION_PIXEL_NAME = "blinkengage-certification.png"

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


@dataclass(frozen=True, slots=True)
class _Smtp:
    """The mailbox's outbound half, coerced once.

    Every path that opens SMTP from this file — the wizard's check, the
    diagnostics probe and the certification send — reads the same values the
    same way, because a check that interpreted them more sensibly than the
    code that actually sends the mail would pass a channel that cannot send,
    and that is the one result any of them must never produce.

    ``port`` stays raw. ``int()`` on a value a customer typed is a failure
    worth reporting rather than one worth raising here, so each caller
    coerces it inside its own guard and shows what was configured either way.
    """

    host: str
    port: Any
    use_tls: bool
    username: str
    password: str
    #: The address mail leaves as, under the same fallback
    #: ``EmailProvider.send_message`` applies — so a certification send is
    #: addressed by whatever the real send path would have used, including
    #: the case where that turns out to be nothing at all.
    sender: str

    @classmethod
    def of(cls, credentials: dict[str, Any]) -> _Smtp:
        return cls(
            host=str(credentials.get("smtp_host") or ""),
            port=credentials.get("smtp_port", _DEFAULT_SMTP_PORT),
            # ``bool("false")`` is ``True`` here, exactly as it is in
            # ``EmailProvider``. The quirk is copied deliberately: this is the
            # value the send path will use, not the value it ought to use.
            use_tls=bool(credentials.get("smtp_use_tls", True)),
            username=str(credentials.get("smtp_username") or ""),
            password=str(credentials.get("smtp_password") or ""),
            sender=str(
                credentials.get("from_address", credentials.get("smtp_username", "")) or ""
            ),
        )

    @property
    def params(self) -> dict[str, str]:
        """What was configured, for a line of copy to interpolate."""
        return {"host": self.host, "port": str(self.port), "tls": str(self.use_tls).lower()}


def _redact(value: object, credentials: dict[str, Any]) -> str:
    """The server's own words, with the customer's secrets removed.

    A line that says only "could not connect" sends the customer to their
    mail administrator with nothing; "certificate verify failed" and "name or
    service not known" are different problems with different owners. The text
    is the mail server's, not ours, so it is the one thing on these screens
    that is not a translation key — and because it is quoted verbatim it goes
    through the same redaction that keeps provider errors from turning stored
    diagnostics into a credential leak.

    Takes anything printable, not only an exception: a rejected-recipient map
    and an accepted server response are quoted back for the same reason and
    must go through the same filter on the way.
    """
    return redact_credentials(str(value), credentials)[:_MAX_DETAIL_CHARS]


def _with_detail(
    params: dict[str, str], exc: Exception, credentials: dict[str, Any]
) -> dict[str, str]:
    """``params`` plus the server's redacted answer, for a rendered line."""
    return {**params, "detail": _redact(exc, credentials)}


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
    smtp = _Smtp.of(credentials)
    params = smtp.params

    try:
        async with aiosmtplib.SMTP(
            hostname=smtp.host,
            port=int(smtp.port),
            use_tls=smtp.use_tls,
            timeout=_PROBE_TIMEOUT_SECONDS,
        ) as client:
            await client.noop()
            if not smtp.username:
                # An unauthenticated relay has no login to report on, and a
                # green line saying so would imply a check that never ran.
                return (ValidationResult(ValidationCode.OK, channel_type="email", params=params),)
            try:
                await client.login(smtp.username, smtp.password)
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
            mismatched = _tls_and_port_disagree(smtp.port, use_tls=smtp.use_tls)
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
    smtp = _Smtp.of(credentials)
    params = smtp.params

    if not smtp.host:
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
            hostname=smtp.host,
            port=int(smtp.port),
            use_tls=smtp.use_tls,
            timeout=_PROBE_TIMEOUT_SECONDS,
        ) as client:
            await client.noop()
            # Read here, inside the session: closing resets the client's
            # record of the greeting, so a version read afterwards would
            # always say the server speaks nothing.
            protocol = _esmtp_diagnostic(
                esmtp=client.last_ehlo_response is not None, params=params
            )
            if not smtp.username:
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
                await client.login(smtp.username, smtp.password)
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


# --- Certification ---------------------------------------------------------
#
# Everything below runs only when the runner has already decided it may.
# ``NOT_SUPPORTED`` (the manifest never claimed it) and the two safety skips
# (would put a message in front of a person, would change the channel's state)
# are settled before any of this is called, and none of it is re-checked here:
# a connector that re-litigated the runner's judgement would be a connector
# choosing its own denominator.
#
# The one thing every function here shares is that it returns what it
# measured. There is no path through this section that reports ``PASS``
# without a server having answered — including the fall-through, which skips.


def _skipped(kind: ScenarioKind, detail_key: str, **params: str) -> ScenarioResult:
    """A scenario this connector cannot exercise, said out loud.

    ``SKIPPED`` costs coverage and leaves the score alone, which is the
    correct price: an unexecuted scenario is an unanswered question, and the
    alternative — a pass for a thing nobody ran — is the failure mode the
    whole certification module exists to prevent. Every use of this carries a
    reason, because "skipped" with no reason is indistinguishable from a
    connector that could not be bothered.
    """
    return ScenarioResult(
        kind=kind, outcome=Outcome.SKIPPED, detail_key=detail_key, params=params
    )


def _failed(
    kind: ScenarioKind, detail_key: str, params: dict[str, str], diagnostics: dict[str, str]
) -> ScenarioResult:
    return ScenarioResult(
        kind=kind,
        outcome=Outcome.FAIL,
        detail_key=detail_key,
        params=params,
        diagnostics=diagnostics,
    )


async def _certify_authentication(credentials: dict[str, Any]) -> ScenarioResult:
    """The diagnostics probe, scored.

    Deliberately not a second implementation. ``diagnose`` already opens the
    session the send path opens and decides what it proved; writing that again
    here would give this channel two probes that could disagree about the same
    mailbox — and the day they disagreed, the panel and the certificate would
    be telling one support engineer two different things about one server.

    The mapping is the only new judgement, and it is one line each: a refused
    connection or a refused password is a ``FAIL``, a server that answered
    without ESMTP is a ``WARNING`` (it worked — and what is worth saying is
    that this mailbox has no ``AUTH`` and no ``STARTTLS``, so the mail leaves
    in the clear), and an accepted credential is a ``PASS``.
    """
    kind = ScenarioKind.AUTHENTICATION
    measured = {item.key: item for item in await _diagnose_smtp(credentials)}
    auth = measured.get(DiagnosticKey.AUTHENTICATION)
    protocol = measured.get(DiagnosticKey.API_VERSION)
    if auth is None:  # pragma: no cover - the probe answers this key on every path
        # If that ever stops being true, the honest report is that nothing was
        # measured. The fall-through of this function is a skip, never a pass.
        return _skipped(kind, _CERT_NOT_MEASURED)

    # ``detail`` is the server's own redacted words. It belongs in evidence,
    # not in the parameters a translated line interpolates.
    params = {name: value for name, value in auth.params.items() if name != "detail"}
    diagnostics: dict[str, str] = {}
    if server_said := auth.params.get("detail"):
        diagnostics["error"] = server_said
    if protocol is not None and protocol.value:
        diagnostics["server_protocol"] = protocol.value

    if auth.status is DiagnosticStatus.FAIL:
        return _failed(kind, auth.detail_key or "", params, diagnostics)
    if protocol is not None and protocol.status is DiagnosticStatus.WARN:
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.WARNING,
            detail_key=protocol.detail_key,
            params=params,
            # The authentication verdict is kept beside the warning: the row
            # now leads with the protocol finding, and a reader must still be
            # able to see that the credential itself was accepted.
            diagnostics={**diagnostics, "authentication": auth.detail_key or ""},
        )
    return ScenarioResult(
        kind=kind,
        outcome=Outcome.PASS,
        detail_key=auth.detail_key,
        params=params,
        diagnostics=diagnostics,
    )


def _certification_message(
    smtp: _Smtp, *, recipient: str, origin: str, attachment: bool
) -> EmailMessage:
    """The mail a certification run actually sends.

    Built the way ``EmailProvider.send_message`` builds one — same sender
    fallback, same ``Message-ID`` shape, same ``add_attachment`` call — so
    what is proven here is the message the send path would really produce and
    not a simpler one that happens to be easier to get accepted.
    """
    message = EmailMessage()
    message["From"] = smtp.sender
    message["To"] = recipient
    message["Subject"] = _CERTIFICATION_SUBJECT
    message["Message-ID"] = f"<{uuid4()}@{smtp.host}>"
    message["Auto-Submitted"] = _AUTO_SUBMITTED
    message[_CERTIFICATION_HEADER] = "1"
    message.set_content(_CERTIFICATION_BODY.format(origin=origin))
    if attachment:
        message.add_attachment(
            _CERTIFICATION_PIXEL,
            maintype="image",
            subtype="png",
            filename=_CERTIFICATION_PIXEL_NAME,
        )
    return message


async def _certify_send(
    kind: ScenarioKind, credentials: dict[str, Any], *, target: str | None, origin: str
) -> ScenarioResult:
    """Send real mail, and report what the server said about it.

    This is the one place in this file that puts something in somebody's
    inbox. It is reached only because the runner was given a target by name,
    and it sends to that address and to nothing else — no fallback, no last
    known customer, no ``from_address`` standing in for a missing target.

    ``MEDIA_UPLOAD`` is the same send with an attachment, because on this
    channel that is what uploading media *is*: there is no upload endpoint and
    no media id: the bytes travel inside the message, so the only thing that
    can be proven about them is that a mail server accepted a message carrying
    them. Two scenarios, one code path, one difference — which is honest,
    where a separate ``MEDIA_UPLOAD`` implementation that skipped the send
    would be certifying a step this channel does not have.
    """
    attachment = kind is ScenarioKind.MEDIA_UPLOAD
    accepted_key = _CERT_MEDIA_ACCEPTED if attachment else _CERT_SEND_ACCEPTED
    rejected_key = _CERT_MEDIA_REJECTED if attachment else _CERT_SEND_REJECTED
    smtp = _Smtp.of(credentials)
    params = smtp.params

    if not target:
        # The runner does not call an emitting scenario without one, so this
        # is not a second opinion on its judgement — it is the last guard in
        # front of an irreversible action, and the reason the type below is
        # a ``str``. Its key is the runner's own, so a report cannot end up
        # with two different sentences for one situation.
        return _skipped(kind, "certification.skipped.noTarget")
    _, recipient = parseaddr(target)
    if "@" not in recipient:
        # A target that is not an address is not a broken channel, and
        # failing it would report one. This is the shared field an operator
        # types a phone number into for the SMS channel and forgets to change.
        return _skipped(kind, _CERT_TARGET_NOT_AN_ADDRESS)
    if not smtp.host:
        # The same guard ``_diagnose_smtp`` makes, and here it matters more:
        # ``aiosmtplib`` resolves an empty hostname to the local machine, so
        # sending without one would hand real mail to whatever MTA happens to
        # be listening beside this process — from an address this customer
        # owns, out of a server they have never heard of.
        return _failed(kind, _DIAG_SMTP_HOST_MISSING, params, {})
    if not smtp.sender:
        # Mail with no ``From`` is mail every receiving server treats as spam,
        # and ``from_address`` is a required field precisely so this cannot
        # happen. A blob that reaches here without one is a channel that
        # cannot send, which is a failure and not a skip.
        return _failed(kind, _CERT_SEND_NO_SENDER, params, {})

    try:
        message = _certification_message(
            smtp, recipient=recipient, origin=origin, attachment=attachment
        )
    except Exception as exc:
        # A stored ``from_address`` with a stray newline in it is a header the
        # email package refuses to build, and refusing is right — that is a
        # header injection. But it is also the one line in this function that
        # can raise before a socket is opened, and a raise reaches the runner
        # as ``certification.raised``: a failure with no explanation, on a
        # contract that says return a result. So it is caught and named.
        return _failed(kind, _CERT_SEND_MALFORMED, params, {"error": _redact(exc, credentials)})

    # The ``Message-ID`` is deliberately *not* in here yet. It is evidence of a
    # message that exists, and a run that never got past the login handed
    # nothing to anybody — an id in that report is one a support engineer
    # would go looking for in a mail log that has never seen it.
    evidence: dict[str, str] = {"recipient": recipient}
    if attachment:
        evidence["attachment"] = f"image/png {len(_CERTIFICATION_PIXEL)}B"

    finding: ScenarioResult | None = None
    try:
        async with aiosmtplib.SMTP(
            hostname=smtp.host,
            port=int(smtp.port),
            use_tls=smtp.use_tls,
            timeout=_SCENARIO_TIMEOUT_SECONDS,
        ) as client:
            if smtp.username:
                try:
                    await client.login(smtp.username, smtp.password)
                except Exception as exc:
                    finding = _failed(
                        kind,
                        _DIAG_SMTP_REJECTED,
                        params,
                        {**evidence, "error": _redact(exc, credentials)},
                    )
            if finding is None:
                # From here the message has been offered to the server, so its
                # id is worth reporting either way: on a rejection it is what
                # correlates this run with the line in the server's own log.
                evidence["message_id"] = str(message["Message-ID"])
                try:
                    refused, response = await client.send_message(message)
                except Exception as exc:
                    # Everything from "message too large" to a content filter
                    # to a relay that will not accept this sender. The
                    # server's own words are the useful part and they are in
                    # the evidence; the key says only which step refused.
                    finding = _failed(
                        kind,
                        rejected_key,
                        params,
                        {**evidence, "error": _redact(exc, credentials)},
                    )
                else:
                    evidence["smtp_response"] = _redact(response, credentials)
                    if refused:
                        # ``aiosmtplib`` raises when *every* recipient is
                        # refused, so reaching here means some were accepted
                        # and some were not. With one recipient that cannot
                        # happen today — but the dict is what the call
                        # returned, and ignoring a returned error because the
                        # current caller should not see one is how a silent
                        # partial failure gets certified as a clean pass.
                        finding = ScenarioResult(
                            kind=kind,
                            outcome=Outcome.WARNING,
                            detail_key=_CERT_SEND_PARTIAL,
                            params=params,
                            diagnostics={
                                **evidence,
                                "refused": _redact(refused, credentials),
                            },
                        )
                    else:
                        finding = ScenarioResult(
                            kind=kind,
                            outcome=Outcome.PASS,
                            detail_key=accepted_key,
                            params=params,
                            diagnostics=evidence,
                        )
    except Exception as exc:
        if finding is None:
            return _failed(
                kind,
                _DIAG_SMTP_UNREACHABLE,
                params,
                {**evidence, "error": _redact(exc, credentials)},
            )
        # The message was already handed over when this fired, so it is a
        # session that failed to close cleanly and not a send that failed.
        # Reporting it as a failure would retract a delivery that happened.
        return replace(
            finding,
            diagnostics={**finding.diagnostics, "teardown": _redact(exc, credentials)},
        )
    return finding


class _FolderNotSelectable(Exception):
    """EXAMINE was answered with ``NO``.

    Its own type because ``imaplib`` does not raise for it — a mailbox that
    does not exist comes back as an ordinary tagged ``NO`` and
    ``_fetch_unseen_sync`` walks straight past it into a search that finds
    nothing, forever. That is the failure this scenario exists to catch, so it
    must not be indistinguishable from a socket error.
    """


class _SearchRefused(Exception):
    """SELECT worked and SEARCH did not — the poll's next step."""


def _first_line(data: list[Any] | None) -> str:
    """The first thing the IMAP server said, as text."""
    if not data or data[0] is None:
        return ""
    answer = data[0]
    return (
        answer.decode(errors="replace") if isinstance(answer, bytes) else str(answer)
    )[:_MAX_DETAIL_CHARS]


def _examine_folder_sync(
    host: str, port: int, username: str, password: str, use_ssl: bool, folder: str
) -> dict[str, str]:
    """Log in, open the polled folder read-only, and count what is in it.

    Runs on a worker thread, because ``imaplib`` is synchronous — the same
    pattern ``EmailProvider._check_imap`` and ``email_imap_poll_task`` already
    use, rather than a second way of reaching IMAP.

    ``EXAMINE`` rather than ``SELECT``, and this is the important line in this
    function. The poll marks every message it fetches ``\\Seen``, which is
    exactly how it avoids fetching one twice — so a certification run that
    opened the mailbox for writing could consume a customer's unread mail to
    prove that it could read it. Read-only, no ``FETCH``, and the connection
    is closed with ``LOGOUT`` rather than ``CLOSE``: nothing here changes a
    flag, and nothing here expunges anything.
    """
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    connection = imap_cls(host, port, timeout=_SCENARIO_TIMEOUT_SECONDS)
    try:
        # Raises ``IMAP4.error`` when the credential is rejected.
        connection.login(username, password)
        selected, mailbox = connection.select(folder, readonly=True)
        if selected != "OK":
            raise _FolderNotSelectable(_first_line(mailbox))
        found, unseen = connection.search(None, "UNSEEN")
        if found != "OK":
            raise _SearchRefused(_first_line(unseen))
        return {
            "folder": folder,
            "messages": _first_line(mailbox) or "0",
            "unseen": str(len(unseen[0].split()) if unseen and unseen[0] else 0),
        }
    finally:
        with contextlib.suppress(Exception):
            connection.logout()


async def _certify_receive(credentials: dict[str, Any]) -> ScenarioResult:
    """Prove the mailbox the poll reads can be read.

    Whether this deserves a ``PASS`` for "can receive" is the one genuinely
    arguable call in this file, so here is the argument.

    What it does not do is receive a message. Nothing can, on demand: a
    message arrives when somebody sends one, and manufacturing one would mean
    sending mail into a customer's live mailbox and then consuming it, which
    is both a message this run had no business creating and a deletion of
    somebody's unread mail.

    What it does do is execute every step of the inbound path that involves
    the provider at all. ``email_imap_poll_task`` logs in, selects the
    configured folder and searches it; this logs in, selects the configured
    folder read-only and searches it. Past that point the poll is fetching
    bytes and handing them to ``EmailProvider.receive_message`` — our own MIME
    parser, running in our own process, covered by our own tests. There is no
    remaining provider behaviour that a real message would exercise and this
    does not.

    So the honest reading is that the inbound *channel* is proven and the
    parse is not in question, which is a pass — and the detail key says
    ``mailboxReadableNoMessageFetched`` precisely so the row cannot be read as
    more than that. The alternative, a permanent ``WARNING`` on every
    correctly configured mailbox, is the mistake this connector already argues
    against twice: a warning that fires on something demonstrably working is
    how a report teaches people to stop reading it.

    The failures are worth as much as the pass. A host with no password, or
    with a folder the customer's own rules move mail out of, is a channel
    whose outbound is green, whose health is green, and into which every reply
    a customer sends disappears silently. That is this channel's most common
    real fault, and before this scenario nothing in the product measured it.
    """
    kind = ScenarioKind.RECEIVE_MESSAGE
    host = str(credentials.get("imap_host") or "")
    folder = str(credentials.get("imap_folder") or "INBOX")
    params = {"host": host, "folder": folder}
    if not host:
        # Send-only is a legitimate configuration — statements, reminders,
        # notifications — so there is nothing here to fail. There is also
        # nothing to read, and saying it ran would be a fabrication.
        return _skipped(kind, _CERT_RECEIVE_SEND_ONLY)

    try:
        evidence = await to_thread.run_sync(
            _examine_folder_sync,
            host,
            int(credentials.get("imap_port", _DEFAULT_IMAP_PORT)),
            str(credentials.get("imap_username") or ""),
            str(credentials.get("imap_password") or ""),
            bool(credentials.get("imap_use_ssl", True)),
            folder,
        )
    except _FolderNotSelectable as exc:
        return _failed(
            kind, _CERT_RECEIVE_FOLDER_UNSELECTABLE, params, {"error": _redact(exc, credentials)}
        )
    except _SearchRefused as exc:
        return _failed(
            kind, _CERT_RECEIVE_SEARCH_REFUSED, params, {"error": _redact(exc, credentials)}
        )
    except Exception as exc:
        # Split the same way ``EmailProvider._check_imap`` splits it: a
        # protocol error is overwhelmingly a rejected login, and anything else
        # — including a port that will not parse — never reached a server.
        return _failed(
            kind,
            _CERT_RECEIVE_LOGIN_REJECTED
            if isinstance(exc, imaplib.IMAP4.error)
            else _CERT_RECEIVE_UNREACHABLE,
            params,
            {"error": _redact(exc, credentials)},
        )
    return ScenarioResult(
        kind=kind,
        outcome=Outcome.PASS,
        detail_key=_CERT_RECEIVE_READABLE,
        params=params,
        diagnostics=evidence,
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

    async def run_scenario(
        self,
        kind: ScenarioKind,
        *,
        credentials: dict[str, Any],
        context: DeploymentContext,
        target: str | None = None,
        webhook_secret: str | None = None,
        callback_url: str | None = None,
        external_id: str | None = None,
        external_parent_id: str | None = None,
    ) -> ScenarioResult:
        """Demonstrate what this mailbox can be made to demonstrate.

        Four scenarios are executed against the real server — the SMTP
        session, a send, a send carrying an attachment, and a read of the
        folder the inbound poll reads. The rest return ``SKIPPED`` with the
        reason, which is the whole discipline: this connector would score
        better by returning ``PASS`` for a webhook it does not have and a
        reconnect it cannot perform, and every one of those passes would be a
        sentence certifying a channel nobody had tested.

        ``WEBHOOK_DELIVERY`` arrives here because the scenario has no feature
        behind it, so it applies to every connector. The manifest above was
        checked rather than remembered: ``capabilities`` holds
        ``MANUAL_CONFIGURATION`` and ``HEALTH_CHECKS`` and no
        ``Capability.WEBHOOKS``, and there is correspondingly nothing in this
        file that registers a callback or signs one. So the answer is neither
        a failure (nothing is broken; inbound arrives by IMAP poll, by
        design) nor ``NOT_SUPPORTED`` (that verdict is the runner's, and a
        connector returning it would be excluding itself from its own
        denominator) but a skip that says which of the two it is. A connector
        that ever declares ``WEBHOOKS`` has to revisit this row.

        ``context`` is read for the first time on this channel, and for one
        line: the mail this method sends says which installation sent it, so
        whoever opens a test message in an inbox they did not expect one in
        can tell where it came from.
        """
        match kind:
            case ScenarioKind.AUTHENTICATION:
                return await _certify_authentication(credentials)
            case ScenarioKind.SEND_MESSAGE | ScenarioKind.MEDIA_UPLOAD:
                return await _certify_send(
                    kind, credentials, target=target, origin=context.public_base_url
                )
            case ScenarioKind.RECEIVE_MESSAGE:
                return await _certify_receive(credentials)
            case ScenarioKind.MEDIA_DOWNLOAD:
                # Nothing to fetch. Inbound media is whatever a customer
                # attached to a message they sent, and the only copies are in
                # their mailbox — reading one to prove that we could is a
                # thing a certification run has no standing to do, and the
                # poll's ``\Seen`` flag would consume it on the way past.
                # Selecting the folder proves the transport, which is the
                # RECEIVE_MESSAGE row; it does not prove the MIME walk, and
                # claiming it did would certify code that never ran.
                return _skipped(kind, _CERT_NO_INBOUND_MEDIA)
            case ScenarioKind.WEBHOOK_DELIVERY:
                return _skipped(
                    kind, _CERT_NO_WEBHOOK, folder=str(credentials.get("imap_folder") or "INBOX")
                )
            case ScenarioKind.TOKEN_REFRESH:
                # There is no token. A password has no expiry we can see and
                # no renewal we could perform unattended, which is why this
                # connector declares no ``TOKEN_REFRESH`` capability either —
                # when a provider revokes an app password the fix is a human
                # generating another one.
                return _skipped(kind, _CERT_NO_TOKEN)
            case ScenarioKind.DISCONNECT | ScenarioKind.RECONNECT:
                # A mailbox holds nothing on our behalf: no session, no
                # subscription, no registration, no grant to revoke. There is
                # therefore nothing to tear down, and "reconnecting" would be
                # opening the SMTP session ``AUTHENTICATION`` has already
                # opened and reporting it a second time under another name —
                # which is how a suite doubles its own score without
                # measuring anything twice.
                return _skipped(kind, _CERT_NO_SESSION)
            case _:
                # READ_RECEIPT and TYPING_INDICATOR, which the runner reports
                # as NOT_SUPPORTED and never sends here — the manifest claims
                # neither. If a manifest change ever routes one through,
                # ``EmailProvider.mark_as_read`` and ``typing_indicator``
                # return ``None`` without calling anything, so the honest
                # answer is that there is nothing to execute. A skip, because
                # the fall-through of this method must never be a pass.
                return _skipped(kind, _CERT_PROVIDER_NO_OP)

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
