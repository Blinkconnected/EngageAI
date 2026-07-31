"""``TelegramConnector`` — the channel that is one field wide, and why.

Telegram is the case the capability contract most needed to survive: there
is no consent screen to redirect a customer to, no application to register
with Telegram, and no directory of things the customer owns. A bot *is* its
token, handed over by BotFather in a chat window. So ``MANUAL_CONFIGURATION``
is the only way in here — and for this channel that is not the degraded path
it is elsewhere, it is the whole product. Which is why the form is one field
and carries the ``/newbot`` command beside it: the promise that a customer
never opens a provider's documentation has to be kept without OAuth doing the
work, and the only thing standing between a customer and a bot token is
knowing which four characters to type into a chat.

What is left undeclared matters as much as what is declared.

``OAUTH`` is absent because Telegram has none. Declaring it and raising from
``authorize_url`` would put an Authenticate-by-redirect step in front of a
customer with nowhere to be sent — the flow is derived from the capability
set, so an optimistic declaration is not an unused method, it is a broken
screen.

``AUTO_DISCOVERY`` is absent because a token names exactly one bot. ``getMe``
does answer "which bot is this?", but that is confirmation rather than
choice, and a picker with a single row is a click this flow cannot afford.
The confirmation still happens, in the place that costs nothing: a line on
the checklist.

``TOKEN_REFRESH`` is absent because bot tokens do not expire. They are
revoked — deliberately, by the customer, in BotFather — which is an event no
refresh loop can anticipate and no stored refresh material could survive.
Declaring it would turn "somebody revoked your bot's token" into a warning
the platform quietly promises to repair by itself, and the honest treatment
is a failed check that says go and get a new one.

``AUTOMATIC_WEBHOOK_REGISTRATION`` is declared, and this is the channel where
it is unambiguously true rather than merely convenient. Telegram has no
dashboard with a callback-URL field in it; ``setWebhook`` is the only
registration mechanism that exists at all. Elsewhere the capability saves a
customer a trip to somebody's developer console — here it is the difference
between a bot that delivers and a bot whose updates pile up in a queue
nobody drains, with nothing anywhere to tell the customer why.

That registration happens in ``register_webhook`` and nowhere else. Telegram's
callback URL names the channel row, and the row does not exist until
``connect`` has returned, so a registration performed inside ``connect`` can
only point Telegram at an id nobody has issued — which is exactly what this
connector used to do, and why the capability could not honestly be declared
until the contract grew a hook that runs after the row is written.

None of that depends on the installation holding a provider app, so the
inherited ``resolve`` reports every declared capability available on a bare
self-hosted deployment exactly as it does on a hosted one. Telegram is the
one channel whose flow is the same everywhere, which makes it the useful
control when a capability difference shows up in another connector.

**The feature matrix is read off ``TelegramProvider``, not off the Bot API.**
What Telegram can do and what this platform does with it are different lists,
and the customer is promised the second one. So ``MEDIA`` is qualified rather
than ticked — the provider sends any attachment (photos as photos, everything
else as a document) but *receives* only ``photo`` and ``document``, so an
inbound video or voice note arrives as its caption and nothing else.
``EDIT_MESSAGES`` and ``DELETE_MESSAGES`` are outbound-only because
``receive_message`` returns nothing for an ``edited_message`` update: we can
edit what we sent, and never learn that the customer edited what they sent.
``TYPING_INDICATORS`` is outbound-only because the Bot API has no update that
tells a bot a human is typing. ``READ_RECEIPTS`` is absent because
``mark_as_read`` is a deliberate no-op, and reactions, templates, broadcasts,
interactive messages and calls are absent because nothing here implements
them. A matrix that ticked those would be worse than no matrix: it would be
believed.

**Diagnostics answer more here than anywhere else**, because ``getWebhookInfo``
is a provider genuinely reporting on itself — whether it holds a webhook for
this bot, whose host it is pointing at, when it last failed to deliver and how
many updates are waiting. Everything this connector reports is something
Telegram said in that call or in ``getMe``; nothing is inferred, and the keys
it cannot measure (permissions, rate-limit headroom, response times) are left
for the platform to fill with ``UNKNOWN`` rather than answered optimistically.

**Certification is where "it is configured" and "it works" stop being the
same sentence**, and Telegram can pay for more of that difference than any
other connector here: ``getMe``, ``getWebhookInfo``, ``sendMessage``,
``sendPhoto``, ``sendChatAction`` and ``getFile`` are all reachable with
nothing but a bot token and, where something is going to be sent, a chat id
somebody typed on purpose. Seven of the eleven scenarios genuinely execute.

The other four are the ones worth reading, because each is a place a
plausible-looking ``PASS`` was available and not taken:

- ``RECEIVE_MESSAGE`` cannot be made to happen. Nothing here can cause a
  customer to message the bot, and the webhook evidence that looks like proof
  is proof of something else — see ``_prove_receiving``.
- ``TOKEN_REFRESH`` has nothing to refresh: bot tokens do not expire, they are
  revoked in BotFather. That is reported as unexecuted rather than as
  inapplicable, because deciding a scenario does not apply is deciding one's
  own denominator, and that judgement belongs to the runner.
- ``DISCONNECT`` and ``RECONNECT`` are one call each — ``deleteWebhook`` and
  ``setWebhook`` — and both would leave this channel silently deaf. Telegram
  holds ``secret_token`` write-only: ``getWebhookInfo`` never returns it, so a
  re-registration must supply a *new* one, and a scenario has no way to hand
  that back for the ``webhook_secret`` column the way ``Repair`` does. The
  webhook would come back looking healthy while every update failed signature
  verification. See ``_prove_reconnection``.

Everything customer-visible below is a translation key, and every string
that starts life inside an exception goes through ``error_sanitizer`` first:
this provider carries its bot token in the request URL, so an unsanitised
``httpx`` error message is a live credential written into whatever storage
the caller happens to keep failures in.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    DeploymentContext,
    Repair,
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
    DocumentationLink,
    RepairAction,
    ValidationCode,
    ValidationResult,
    VerificationSpec,
)
from blinkengage.domain.connectors import (
    Capability,
)
from blinkengage.domain.exceptions import DomainError, InvalidChannelCredentialsError
from blinkengage.infrastructure.channels.error_sanitizer import redact_credentials
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: Matches ``TelegramProvider``'s own default. Not offered as a form field:
#: the two override keys the provider accepts (``api_base_url``,
#: ``file_base_url``) exist for tests and for a local Bot API server, and
#: putting either in front of a customer would be asking them a question
#: they have no way to answer.
_API_BASE_URL = "https://api.telegram.org"

#: Every call here is a single small JSON round trip. Ten seconds is long
#: enough for a slow network and short enough that a customer watching the
#: checklist learns something before they give up on it.
_TIMEOUT = httpx.Timeout(10.0)

#: Where Telegram serves the bytes ``getFile`` names, matching
#: ``TelegramProvider``'s own default. A second base URL rather than a path
#: under the first: the Bot API answers ``/bot<token>/<method>`` and the file
#: service answers ``/file/bot<token>/<path>``, and only the download scenario
#: has any use for the second.
_FILE_BASE_URL = "https://api.telegram.org/file"

#: Tighter, because ``diagnose`` makes *two* calls and the platform gives a
#: connector one budget for the whole report — a panel that hangs waiting for
#: a connector fails at the exact moment an unreachable provider is what the
#: support engineer is trying to establish. Two of these fit inside that
#: budget with room to spare; two of ``_TIMEOUT`` do not.
_DIAGNOSE_TIMEOUT = httpx.Timeout(5.0)

#: Tighter again, for certification. The runner allows one scenario twenty
#: seconds and moves on, and the longest scenario here spends up to four round
#: trips (``getChat``, ``getUserProfilePhotos``, ``getFile``, then the file
#: itself) — four of these fit inside that budget, and two of ``_TIMEOUT``
#: already do not.
_SCENARIO_TIMEOUT = httpx.Timeout(5.0)

#: How recently Telegram must have failed a delivery for the failure to be
#: describing the present rather than a bad afternoon last month. Telegram
#: reports the last delivery it could *not* make and never reports one it
#: could, so the age of that failure — together with the queue sitting behind
#: it — is the only evidence available that delivery has since recovered. A
#: day, because anything shorter calls a webhook healthy while it is still
#: inside its own retry window.
_RECENT_FAILURE = timedelta(hours=24)

#: Telegram's own throttle response. Its body carries ``retry_after``, which
#: is the only rate-limit figure the Bot API ever states — there are no
#: headroom headers on a successful call, which is why ``RATE_LIMITS`` is
#: answered when we are being throttled and never otherwise.
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500

#: The only status the file service answering with a body means anything on.
#: Its 302s and 404s are not JSON and carry no ``ok`` flag to read, so the
#: download scenario judges it by status and size alone.
_OK = 200

#: Updates in flight during a burst are ordinary; a queue that has grown past
#: this is something nobody is draining. A threshold rather than "any pending
#: update is a warning", because a panel that flickers amber whenever a
#: customer sends two messages at once is a panel nobody reads.
_PENDING_UPDATE_BACKLOG = 10

#: 32 bytes of urlsafe randomness, sent to Telegram as ``secret_token`` and
#: returned for storage. Telegram echoes it on every delivery in
#: ``X-Telegram-Bot-Api-Secret-Token``, which is the entirety of what
#: ``TelegramProvider.verify_signature`` has to work with — there is no
#: payload signature, so this value is the only thing separating a real
#: update from anyone who guesses a webhook URL.
_SECRET_BYTES = 32

_REREGISTER_WEBHOOK = "reregister_webhook"

_CHECK_TOKEN = "connect.telegram.check.token"
_CHECK_IDENTITY = "connect.telegram.check.identity"
_CHECK_DELIVERY = "connect.telegram.check.delivery"
_CHECK_REACHABLE = "connect.telegram.check.reachable"

_FIX_ISSUE_TOKEN = "connect.telegram.fix.issueToken"

#: Qualifications on the feature matrix. Each exists because the honest
#: answer is "yes, but", and a matrix that rounded those up to "yes" is how a
#: customer discovers the limit by hitting it in front of their own customer.
#: Media: photos and documents in both directions, and inbound video, audio,
#: voice notes and stickers arriving as text only.
_FEATURE_MEDIA_NOTE = "connect.telegram.feature.media.note"
#: Typing: ``sendChatAction`` shows the indicator for a few seconds and
#: expires on its own — there is no call that stops it early, so
#: ``typing_indicator(is_typing=False)`` has nothing to send.
_FEATURE_TYPING_NOTE = "connect.telegram.feature.typing.note"
#: Edit: ``editMessageText`` replaces text. The caption of a photo or
#: document this connector sent is not editable through it.
_FEATURE_EDIT_NOTE = "connect.telegram.feature.edit.note"

#: Diagnostics copy. In the platform's ``diagnostics.*`` namespace rather
#: than this connector's ``connect.*`` one, because they render in the same
#: panel as the platform's own lines and a support engineer reading it should
#: not be able to tell which half produced which row.
_DIAG_TOKEN_MISSING = "diagnostics.telegram.botTokenMissing"
_DIAG_TOKEN_REJECTED = "diagnostics.telegram.botTokenRejected"
_DIAG_AUTHENTICATED = "diagnostics.telegram.authenticatedAs"
_DIAG_UNREACHABLE = "diagnostics.telegram.providerUnreachable"
_DIAG_THROTTLED = "diagnostics.telegram.throttled"
_DIAG_API_UNVERSIONED = "diagnostics.telegram.apiUnversioned"
_DIAG_WEBHOOK_MISSING = "diagnostics.telegram.webhookNotRegistered"
_DIAG_WEBHOOK_ELSEWHERE = "diagnostics.telegram.webhookRegisteredElsewhere"
_DIAG_DELIVERY_FAILURE = "diagnostics.telegram.deliveryFailure"
_DIAG_PENDING_UPDATES = "diagnostics.telegram.pendingUpdates"
_DIAG_PENDING_UNDELIVERABLE = "diagnostics.telegram.pendingUpdatesUndeliverable"

#: The Bot API states no version. There is none in the URL this connector
#: builds (``/bot<token>/<method>``), none in a response header, and no
#: method that returns one — so the version row can never be *measured*, as
#: distinct from merely not having been measured yet. Reported as ``UNKNOWN``
#: carrying the reason, which is strictly more than the ``UNKNOWN`` the
#: platform would fill in for a key nobody answered, and honest in a way that
#: inventing a number to fill the row would not be.
_API_IS_UNVERSIONED = Diagnostic(
    key=DiagnosticKey.API_VERSION,
    status=DiagnosticStatus.UNKNOWN,
    detail_key=_DIAG_API_UNVERSIONED,
)

#: Certification copy, in the platform's ``certification.*`` namespace beside
#: the runner's own ``certification.skipped.noTarget`` — a report has the same
#: rows for every channel, and a reader should not be able to tell which half
#: of the system worded which line.
_CERT_TOKEN_MISSING = "certification.telegram.botTokenMissing"
_CERT_UNREACHABLE = "certification.telegram.providerUnreachable"
_CERT_THROTTLED = "certification.telegram.throttled"
_CERT_REJECTED = "certification.telegram.rejectedByProvider"
_CERT_UNEXPECTED = "certification.telegram.unexpectedFailure"
_CERT_NO_TARGET_CHAT = "certification.telegram.noTargetChat"
_CERT_AUTHENTICATED = "certification.telegram.authenticatedAs"
_CERT_NOT_MEASURED = "certification.telegram.notMeasured"
_CERT_WEBHOOK_REGISTERED = "certification.telegram.webhookRegistered"
_CERT_WEBHOOK_MISSING = "certification.telegram.webhookNotRegistered"
_CERT_WEBHOOK_ELSEWHERE = "certification.telegram.webhookRegisteredElsewhere"
_CERT_WEBHOOK_FAILING = "certification.telegram.webhookDeliveryFailing"
_CERT_WEBHOOK_BACKLOG = "certification.telegram.webhookBacklog"
_CERT_TOKEN_NOT_ACCEPTED = "certification.telegram.tokenNotAccepted"
_CERT_MESSAGE_UNCONFIRMED = "certification.telegram.messageUnconfirmed"
_CERT_PHOTO_UNCONFIRMED = "certification.telegram.photoUnconfirmed"
_CERT_MESSAGE_SENT = "certification.telegram.messageSent"
_CERT_PHOTO_SENT = "certification.telegram.photoSent"
_CERT_TYPING_ACCEPTED = "certification.telegram.chatActionAccepted"
_CERT_FILE_DOWNLOADED = "certification.telegram.fileDownloaded"
_CERT_NO_FILE_TO_DOWNLOAD = "certification.telegram.noFileToDownload"
_CERT_INBOUND_NOT_PROVOKABLE = "certification.telegram.inboundCannotBeProvoked"
_CERT_TOKENS_DO_NOT_EXPIRE = "certification.telegram.botTokensDoNotExpire"
_CERT_SECRET_NOT_RECOVERABLE = "certification.telegram.webhookSecretNotRecoverable"

#: What the emitting scenarios put in front of whoever the operator named.
#: The one customer-visible string in this module that is deliberately *not* a
#: translation key: it is the payload rather than the copy, Telegram delivers
#: it verbatim into a chat window, and a chat id carries no locale to pick a
#: translation with — so a key here would be a slug in front of a human, which
#: is the failure the key convention exists to prevent, arrived at backwards.
_CERTIFICATION_MESSAGE = "BlinkEngage connector certification"

#: A 64×64 PNG, 136 bytes, embedded rather than fetched: ``sendPhoto`` has to
#: be given real bytes to prove the upload path, and a certification run that
#: reached out to some third host for a test image would fail in every
#: air-gapped installation this product is deployed into. Telegram rejects
#: images below a few pixels a side, which is why this is not a 1×1.
_CERTIFICATION_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAT0lEQVR42u3PQQkAAAgEsMticHvZxgi+hcEK"
    "LNXzWgQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQELgvkFpF4VhtebgAA"
    "AABJRU5ErkJggg=="
)
_CERTIFICATION_IMAGE_NAME = "blinkengage-certification.png"

_ERROR_TOKEN_MISSING = "connect.telegram.error.botTokenMissing"
_ERROR_TOKEN_REJECTED = "connect.telegram.error.botTokenRejected"
_ERROR_WEBHOOK_REGISTRATION = "connect.telegram.error.webhookRegistrationFailed"
#: Pressed before there is a channel to deliver to. Only reachable when the
#: delivery warning's fix is offered on the pre-connect checklist, where no
#: row — and therefore no callback URL — exists yet.
_ERROR_CALLBACK_URL_MISSING = "connect.telegram.error.callbackUrlMissing"

#: The same code the base ``Connector`` returns for a repair it does not
#: implement, so a caller need not tell "this connector cannot" from "this
#: connector cannot do *that*".
_REASON_NOT_SUPPORTED = "not_supported"


class TelegramSetupError(DomainError):
    """A Bot API call the connect step depends on did not succeed.

    Carries a translation key and nothing else, for the reason every other
    customer-facing string in this module does: a sentence composed on the
    server is a sentence that can only ever be English. Telegram's own
    ``description`` is deliberately not appended — it names Bot API methods
    and would be the moment the customer starts reading Telegram's
    documentation, which is the failure this whole flow exists to prevent.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Bot:
    """The parts of a ``getMe`` result anything here cares about."""

    id: int
    username: str
    display_name: str


def _bot_token(source: Mapping[str, Any]) -> str:
    """The token, out of one mapping.

    It used to search two, because the contract did not say whether a
    form-based connector's typed values arrived as ``grant`` or as
    ``credentials`` and guessing wrong meant a checklist reporting an
    unreachable bot it had never actually asked about. ``Attempt`` answers
    that: consent material is ``grant``, typed values are ``inputs``, and
    ``Attempt.credentials`` is whichever of the two this connector has — for
    Telegram always ``inputs``, since there is no consent to produce a grant.
    """
    token = source.get("bot_token")
    return token.strip() if isinstance(token, str) else ""


def _bot_from(result: Mapping[str, Any]) -> _Bot:
    username = str(result.get("username") or "")
    bot_id = int(result.get("id") or 0)
    # A bot's ``first_name`` is whatever the customer called it and is the
    # name their agents will see in the channel list; ``@username`` is what
    # their customers type. Preferring the handle keeps the two channels a
    # customer runs from one BotFather account distinguishable, which
    # ``first_name`` (frequently just the company's name, twice) does not.
    display_name = (
        f"@{username}" if username else str(result.get("first_name") or f"telegram:{bot_id}")
    )
    return _Bot(id=bot_id, username=username, display_name=display_name)


def _moment(value: Any) -> datetime | None:
    """A Telegram unix timestamp, when it is one.

    Guarded rather than trusted: a malformed date in one line of a
    diagnostics report must not take the other lines with it, and
    ``fromtimestamp`` raises on values a JSON body can perfectly well carry.
    """
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _redacted(text: str, credentials: Mapping[str, Any], token: str) -> str:
    """Provider text, with every credential value taken out of it.

    Both forms of the token, deliberately. ``_bot_token`` strips whitespace,
    so a token pasted with a trailing newline is stored one way and
    interpolated into the request URL another — redacting only the stored
    value would leave the live credential in an ``httpx.InvalidURL`` message,
    which is the exact leak ``error_sanitizer`` exists to close.
    """
    return redact_credentials(redact_credentials(text, dict(credentials)), {"bot_token": token})


async def _call(
    client: httpx.AsyncClient,
    *,
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> tuple[int, dict[str, Any]]:
    """One Bot API call, as ``(status, body)``.

    The single place in this module where the token is interpolated into a
    URL, and the reason nothing here calls ``raise_for_status``: the
    exception it raises embeds the request URL, token and all. The status
    code is returned instead so callers can tell Telegram rejecting a
    credential (4xx, and 200 with ``ok: false``) from Telegram being
    unwell (5xx) without ever touching an ``httpx`` error string.

    ``files`` switches the request to multipart, which ``sendPhoto`` needs and
    nothing else here does. It lives on this function rather than in the one
    caller so the property above stays true — a second place building
    ``/bot<token>/`` is a second place a token can end up in an error string.
    """
    url = f"{_API_BASE_URL}/bot{token}/{method}"
    if files is not None:
        response = await client.post(url, data=payload or {}, files=files)
    elif payload is None:
        response = await client.get(url)
    else:
        response = await client.post(url, json=payload)
    try:
        body = response.json()
    except ValueError:
        # A proxy or captive portal answering with HTML. Indistinguishable
        # from a provider outage from here, and handled as one.
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


@dataclass(frozen=True, slots=True)
class _Answer:
    """One Bot API call, as a scenario has to read it.

    ``_call`` returns ``(status, body)`` and raises when no response arrived —
    which is the right shape for a flow that can afford to be interrupted, and
    the wrong one for a scenario, whose entire contract is to return a result.
    ``status`` of zero is the case ``_call`` cannot express: nothing answered.
    """

    status: int
    body: dict[str, Any]
    #: Already redacted. Set exactly when no response was received at all.
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.body.get("ok"))

    @property
    def description(self) -> str:
        """Telegram's own account of a refusal. Redact before reporting."""
        return str(self.body.get("description") or "")

    @property
    def result(self) -> dict[str, Any]:
        result = self.body.get("result")
        return result if isinstance(result, dict) else {}


@dataclass(frozen=True, slots=True)
class _Fetched:
    """A file download, as evidence rather than as bytes.

    The content is deliberately dropped at the boundary: the scenario proves
    that Telegram served the file, and holding somebody's attachment in memory
    for one line of a report is a cost with no reader.
    """

    status: int
    size: int = 0
    error: str | None = None


async def _ask(
    client: httpx.AsyncClient,
    *,
    token: str,
    credentials: Mapping[str, Any],
    method: str,
    payload: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> _Answer:
    """``_call``, with the transport failures folded into the answer.

    Deliberately broad, like every other call site in this module: a token
    with a newline in it makes ``httpx`` raise ``InvalidURL`` before a request
    is attempted, and that is not an ``HTTPError``.
    """
    try:
        status, body = await _call(client, token=token, method=method, payload=payload, files=files)
    except Exception as exc:  # noqa: BLE001 - a scenario reports, it never raises
        return _Answer(status=0, body={}, error=_redacted(str(exc), credentials, token))
    return _Answer(status=status, body=body)


async def _fetch_file(
    client: httpx.AsyncClient,
    *,
    token: str,
    credentials: Mapping[str, Any],
    file_path: str,
) -> _Fetched:
    """Pull down what ``getFile`` named, by the route the provider uses.

    The second — and last — place a bot token is interpolated into a URL, for
    the reason the file service is a separate host: ``getFile`` answers with a
    path and nothing else, and the bytes are only reachable under
    ``/file/bot<token>/``. Neither the URL nor the content leaves this
    function; only how much of it arrived.
    """
    try:
        response = await client.get(f"{_FILE_BASE_URL}/bot{token}/{file_path}")
    except Exception as exc:  # noqa: BLE001 - see ``_ask``
        return _Fetched(status=0, error=_redacted(str(exc), credentials, token))
    return _Fetched(status=response.status_code, size=len(response.content))


def _recent(moment: datetime | None) -> bool:
    return moment is not None and datetime.now(UTC) - moment <= _RECENT_FAILURE


def _outcome(
    kind: ScenarioKind,
    outcome: Outcome,
    detail_key: str,
    *,
    params: Mapping[str, str] | None = None,
    diagnostics: Mapping[str, str] | None = None,
) -> ScenarioResult:
    """One result, with the empty evidence dropped.

    ``params`` interpolates into the translated line; ``diagnostics`` is what
    the run learned and is never rendered as copy. Empty values are dropped
    from both rather than reported: a report row reading ``last_error:`` with
    nothing after it is a question about whether the field is broken.

    ``duration_ms`` is left at zero throughout: the runner times the call, and
    a connector reporting its own duration is a connector reporting its own
    performance.
    """
    return ScenarioResult(
        kind=kind,
        outcome=outcome,
        detail_key=detail_key,
        params={key: value for key, value in (params or {}).items() if value},
        diagnostics={key: value for key, value in (diagnostics or {}).items() if value},
    )


def _unmeasured(kind: ScenarioKind, answer: _Answer) -> ScenarioResult | None:
    """``SKIPPED`` when Telegram never gave us an answer to read.

    A dead connection, a 5xx or a 429 is Telegram being unwell or busy, not
    this channel being broken, and a ``FAIL`` would send an operator to repair
    a channel that works — the same judgement ``diagnose`` makes when it
    answers ``UNKNOWN`` rather than red for an unreachable provider.

    It is not a free pass either. ``SKIPPED`` costs *coverage*, so a run
    against a provider that is down comes back ``INCONCLUSIVE`` rather than
    clean, which is the honest reading: an unanswered question, not a good
    answer. ``None`` means Telegram answered and the answer can be judged.
    """
    if answer.error is not None:
        return _outcome(
            kind, Outcome.SKIPPED, _CERT_UNREACHABLE, diagnostics={"error": answer.error}
        )
    if answer.status == _TOO_MANY_REQUESTS:
        parameters = answer.body.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        return _outcome(
            kind,
            Outcome.SKIPPED,
            _CERT_THROTTLED,
            diagnostics={
                "retry_after": str(retry_after) if isinstance(retry_after, int) else "",
            },
        )
    if answer.status >= _SERVER_ERROR:
        return _outcome(
            kind, Outcome.SKIPPED, _CERT_UNREACHABLE, diagnostics={"status": str(answer.status)}
        )
    return None


def _rejected(
    kind: ScenarioKind, answer: _Answer, *, credentials: Mapping[str, Any], token: str
) -> ScenarioResult:
    """Telegram answered, and refused. That is the channel failing.

    Distinct from ``_unmeasured`` in exactly the way that matters: something
    was asked of the provider and the provider said no, which is a scenario
    that ran and did not work. Telegram's ``description`` is kept as evidence
    — through the sanitiser, since it is a provider string — and never used as
    copy: it names Bot API methods and is only ever English.
    """
    return _outcome(
        kind,
        Outcome.FAIL,
        _CERT_REJECTED,
        diagnostics={
            "status": str(answer.status),
            "description": _redacted(answer.description, credentials, token),
        },
    )


def _sent_id(result: Mapping[str, Any]) -> str:
    """The id the platform would have stored for this message.

    ``f"{chat_id}:{message_id}"`` — ``TelegramProvider``'s own composite form,
    so evidence in a certification report can be matched against a real
    ``Message.external_message_id`` rather than merely resembling one.
    """
    chat = result.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id = result.get("message_id")
    if chat_id is None or message_id is None:
        return ""
    return f"{chat_id}:{message_id}"


def _largest_photo_file_id(result: Mapping[str, Any]) -> str:
    """The file id Telegram assigned the bytes we just uploaded.

    Proof the upload landed rather than merely that the request was accepted:
    Telegram only issues one once it holds the file. Largest size last, the
    same end of the same list ``TelegramProvider`` reads inbound.
    """
    photo = result.get("photo")
    if not isinstance(photo, list) or not photo:
        return ""
    largest = photo[-1]
    return str(largest.get("file_id") or "") if isinstance(largest, dict) else ""


def _chat_photo_file_id(result: Mapping[str, Any]) -> str:
    """A file this bot can legitimately download, if the chat has one."""
    photo = result.get("photo")
    if not isinstance(photo, dict):
        return ""
    # The small one: this is a round trip to prove the path works, not to move
    # as many bytes as possible through somebody's certification run.
    return str(photo.get("small_file_id") or photo.get("big_file_id") or "")


def _private_chat_user_id(result: Mapping[str, Any]) -> int | None:
    """The user behind a one-to-one chat, when that is what the target is.

    Read off Telegram's own answer rather than off the target string: only
    ``getChat`` can say whether an id names a person, a group or a channel,
    and ``getUserProfilePhotos`` is meaningless for the last two.
    """
    if str(result.get("type") or "") != "private":
        return None
    chat_id = result.get("id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        return None
    return chat_id


def _profile_photo_file_id(result: Mapping[str, Any]) -> str:
    """The smallest size of the most recent profile photo, if there is one."""
    photos = result.get("photos")
    if not isinstance(photos, list) or not photos:
        return ""
    sizes = photos[0]
    if not isinstance(sizes, list) or not sizes:
        return ""
    smallest = sizes[0]
    return str(smallest.get("file_id") or "") if isinstance(smallest, dict) else ""


@ConnectorRegistry.register("telegram")
class TelegramConnector(Connector):
    channel_type = "telegram"

    #: No provider app, on any installation: there is nothing to register
    #: with Telegram and therefore nothing an operator could configure.
    app_key = None

    #: Everything the console needs, declared once.
    #:
    #: ``copyable="/newbot"`` is the whole trick for this channel. A customer
    #: who has never made a bot does not need Telegram's documentation, they
    #: need four characters to send to BotFather; one who has a bot already
    #: ignores it. Both reach the same field without leaving the page — which
    #: is what OAuth buys elsewhere and what has to be bought by hand here.
    MANIFEST = ConnectorManifest(
        channel_type="telegram",
        name_key="connect.telegram.name",
        description_key="connect.telegram.description",
        category=ConnectorCategory.MESSAGING,
        icon="telegram",
        capabilities=frozenset(
            {
                Capability.MANUAL_CONFIGURATION,
                Capability.WEBHOOKS,
                Capability.AUTOMATIC_WEBHOOK_REGISTRATION,
                Capability.HEALTH_CHECKS,
            }
        ),
        # No OAuth exists for the Bot API — not withheld, absent.
        auth_methods=(AuthMethod.CREDENTIALS,),
        required_credentials=(
            CredentialSpec(
                name="bot_token",
                kind="secret",
                label_key="connect.telegram.botToken.label",
                required=True,
                help_key="connect.telegram.botToken.help",
                # Shape, not prose: the same hint in every language.
                placeholder="123456789:AA...",
                copyable="/newbot",
            ),
        ),
        verification_steps=(
            VerificationSpec(
                key="connect.telegram.check.token",
                title_key="connect.telegram.check.token.title",
                codes=(
                    ValidationCode.OK,
                    ValidationCode.MISSING_CREDENTIAL,
                    ValidationCode.INVALID_TOKEN,
                    ValidationCode.PROVIDER_UNREACHABLE,
                ),
            ),
            VerificationSpec(
                key="connect.telegram.check.delivery",
                title_key="connect.telegram.check.delivery.title",
                codes=(ValidationCode.OK, ValidationCode.ADVISORY),
            ),
        ),
        repair_actions=(
            RepairAction(
                id=_REREGISTER_WEBHOOK,
                title_key="connect.telegram.repair.reregisterWebhook.title",
                description_key="connect.telegram.repair.reregisterWebhook.description",
                # No confirmation: re-pointing a webhook at the URL it should
                # already have is not a decision anybody regrets.
                confirm=False,
            ),
        ),
        # Read off ``TelegramProvider``, method by method, and no further.
        # The old free-string version said ``("text", "images", "documents",
        # "edit", "delete", "typing")`` — six words no console could render
        # into a matrix, with no direction on any of them, which meant the
        # three that are outbound-only ticked as if they were both.
        supported_features=(
            # ``send_message``: ``sendMessage`` for text, and photos and
            # documents when there are attachments.
            FeatureSupport(ChannelFeature.SEND_MESSAGES, Direction.OUTBOUND),
            # ``receive_message``/``webhook``: ``message`` updates. Not
            # ``channel_post``, ``edited_message`` or ``callback_query`` —
            # those return nothing, which is why nothing below claims them.
            FeatureSupport(ChannelFeature.RECEIVE_MESSAGES, Direction.INBOUND),
            # Both, and qualified in both. Outbound, ``image/*`` goes as a
            # photo and everything else as a document. Inbound, only
            # ``photo`` and ``document`` are pulled down: a video, a voice
            # note or a sticker arrives with its caption and no file.
            FeatureSupport(ChannelFeature.MEDIA, Direction.BOTH, note_key=_FEATURE_MEDIA_NOTE),
            # Genuinely both: ``reply_to_message_id`` is set on what we send
            # and ``reply_to_message`` is read off what arrives.
            # INBOUND, not BOTH. The outbound half is unreachable:
            # ``ConversationService.send_reply`` populates
            # ``reply_to_external_message_id`` only for a provider declaring
            # ``supports_invisible_reply_threading``, and ``EmailProvider`` is
            # the only one in the codebase that does. The reply-reference code
            # in this provider is real and never called, so claiming BOTH
            # promises a customer a quoted reply the product cannot send.
            FeatureSupport(ChannelFeature.THREADING, Direction.INBOUND),
            # ``editMessageText``, on messages we sent. Outbound-only in the
            # strong sense: a customer editing their own message produces an
            # ``edited_message`` update, and ``receive_message`` drops it — so
            # claiming ``BOTH`` would promise a change we never even see.
            FeatureSupport(
                ChannelFeature.EDIT_MESSAGES, Direction.OUTBOUND, note_key=_FEATURE_EDIT_NOTE
            ),
            # ``deleteMessage``, likewise ours only. The Bot API sends no
            # update at all when a customer deletes something.
            FeatureSupport(ChannelFeature.DELETE_MESSAGES, Direction.OUTBOUND),
            # ``sendChatAction``. Outbound by nature: no Bot API update ever
            # tells a bot that the human is typing, so an agent will never see
            # this in the direction they might expect.
            FeatureSupport(
                ChannelFeature.TYPING_INDICATORS,
                Direction.OUTBOUND,
                note_key=_FEATURE_TYPING_NOTE,
            ),
            # Deliberately absent, each because the code says so:
            # READ_RECEIPTS   — ``mark_as_read`` is a no-op; the Bot API has
            #                   no read receipt a bot can send or observe.
            # REACTIONS       — nothing sends ``setMessageReaction`` and
            #                   ``message_reaction`` updates are not handled.
            # INTERACTIVE_MESSAGES — no ``reply_markup`` is ever sent and
            #                   ``callback_query`` updates are dropped.
            # TEMPLATES, BROADCASTS, VOICE_CALLS, VIDEO_CALLS — no such
            #                   concept in this provider, or in the Bot API.
        ),
        documentation=(
            DocumentationLink(
                key="connect.telegram.docs.botFather",
                url="https://core.telegram.org/bots#botfather",
            ),
        ),
        # Feature-complete and unproven, which is what BETA is for. Every
        # capability declared above is implemented against the real Bot API
        # and none of it depends on a provider app an operator might not
        # have, so there is no path here that cannot run — which is the bar
        # PREVIEW exists to warn about and this connector clears. What it has
        # not done is carry a customer's traffic. PRODUCTION additionally
        # promises that changes to it stay backwards-compatible, and that is
        # a promise to make after the first real deployment has been survived
        # rather than before it.
        maturity=Maturity.BETA,
        versions=VersionInfo(
            connector="1.0.0",
            # Not a number, because the Bot API does not have one. The URL
            # this connector builds is ``/bot<token>/<method>`` — no version
            # segment, no version header, no method that reports one. Meta's
            # connectors can name ``v21.0`` and warn when it is retired;
            # here there is nothing to name and nothing to be retired, and
            # writing a plausible-looking number into this field would invent
            # exactly the deprecation risk it exists to communicate.
            api="unversioned",
            minimum_platform="1.0.0",
        ),
    )

    @property
    def manifest(self) -> ConnectorManifest:
        return self.MANIFEST

    # --- Verify -------------------------------------------------------

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        """Is the token real, and whose bot is it.

        The second question is the one worth the round trip. A customer with
        two bots — a staging one and the real one — pastes the wrong token
        roughly half the time, and every symptom of that mistake appears
        later and somewhere else: messages arriving at a bot nobody watches.
        Naming the bot back to them at the one moment they can still change
        their mind costs a single ``getMe``.

        Every return is a ``ValidationCode`` this connector's manifest
        declared, so the console always has copy for what comes back.
        """
        token = _bot_token(attempt.credentials)
        if not token:
            return (
                ValidationResult(
                    ValidationCode.MISSING_CREDENTIAL,
                    channel_type=self.channel_type,
                    params={"field": "bot_token"},
                    # No repair action: the fix is one step back to the form
                    # the customer typed this into. ``instructions_key``
                    # carries how to get a token from BotFather, for the
                    # customer who goes back and finds they have none.
                    instructions_key=_FIX_ISSUE_TOKEN,
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                status, body = await _call(client, token=token, method="getMe")
                if status >= 500:
                    # Telegram's problem, not the customer's credential — and
                    # a distinct code, because "try again shortly" and "your
                    # token is wrong" are different instructions.
                    return (
                        ValidationResult(
                            ValidationCode.PROVIDER_UNREACHABLE,
                            channel_type=self.channel_type,
                            params={"status": str(status)},
                        ),
                    )
                if not body.get("ok"):
                    # Telegram rejects a bad token as a 401/404 and,
                    # occasionally, as a 200 whose body says ``ok: false``.
                    # ``TelegramProvider.health_check`` treats that 200 as a
                    # configuration failure; anything else here would let a
                    # channel connect that its own health check will call
                    # broken within the minute.
                    return (
                        ValidationResult(
                            ValidationCode.INVALID_TOKEN,
                            channel_type=self.channel_type,
                            instructions_key=_FIX_ISSUE_TOKEN,
                        ),
                    )

                bot = _bot_from(body.get("result") or {})
                results = [
                    ValidationResult(
                        ValidationCode.OK,
                        channel_type=self.channel_type,
                        params={"username": bot.username, "botName": bot.display_name},
                    )
                ]
                delivery = await self._delivery_check(client, token=token)
                if delivery is not None:
                    results.append(delivery)
                return tuple(results)
        except Exception as exc:  # noqa: BLE001 - validate returns findings, never raises
            # Deliberately broad, for the reason ``safe_health_check`` is: a
            # newline pasted into the token makes httpx raise ``InvalidURL``
            # before a request is attempted, and that is not an
            # ``HTTPError``. Every path out of here is a checklist line.
            return (
                ValidationResult(
                    ValidationCode.PROVIDER_UNREACHABLE,
                    channel_type=self.channel_type,
                    params={"detail": redact_credentials(str(exc), {"bot_token": token})},
                ),
            )

    async def _delivery_check(
        self, client: httpx.AsyncClient, *, token: str
    ) -> ValidationResult | None:
        """Telegram's own account of whether it can reach us — when it has one.

        Reported only when Telegram both has a webhook registered for this
        bot and has failed to deliver to it. Silence otherwise is the point:
        a first-time connect has no webhook yet, and warning that the thing
        the next step creates does not exist would teach a customer that the
        checklist is noise to click past — which is how the one warning that
        mattered gets missed.

        The offered fix is the connector's own ``reregister_webhook`` action,
        which needs a channel to point Telegram at. Pressed from the
        pre-connect checklist — where this warning means a *previous*
        connection of the same bot is failing — there is no row and therefore
        no callback URL, and ``repair`` says so rather than inventing one.
        Connecting re-registers anyway, which is the real resolution there.
        """
        try:
            _status, body = await _call(client, token=token, method="getWebhookInfo")
        except Exception:  # noqa: BLE001 - a missing diagnostic is not a failed check
            return None

        info = body.get("result") or {}
        last_error = info.get("last_error_message")
        if not info.get("url") or not last_error:
            return None
        return ValidationResult(
            # Advisory, not blocking: Telegram is reporting a past delivery
            # failure and the very next step re-registers the webhook, so
            # stopping the customer here would be stopping them for something
            # the flow is about to fix.
            ValidationCode.ADVISORY,
            channel_type=self.channel_type,
            params={"detail": str(last_error)},
            repair_action=_REREGISTER_WEBHOOK,
        )

    # --- Connect ------------------------------------------------------

    async def connect(self, *, company_id: UUID, attempt: Attempt) -> tuple[Connection, ...]:
        """Identify the bot, and return the one channel that results.

        One ``Connection`` always: a token is a bot and a bot is a channel.
        There is no consent here that could have covered several resources
        the way one Meta grant covers a WhatsApp number and two Pages, and
        nothing on ``attempt.selection`` to read — there was no picker.

        ``getMe`` is called again rather than trusted from the checklist —
        it names the channel and supplies the external id, and a customer
        can sit on a summary screen for long enough that a token revoked in
        between would otherwise be persisted as working.

        No ``setWebhook`` here, and no secret minted here either. Both belong
        to ``register_webhook``, which runs once the row exists and is handed
        the URL that actually names it.
        """
        token = _bot_token(attempt.credentials)
        if not token:
            raise InvalidChannelCredentialsError(self.channel_type, _ERROR_TOKEN_MISSING)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            bot = await self._identify(client, token=token)

        return (
            Connection(
                channel_type=self.channel_type,
                # What the customer called it, when they called it anything.
                # Falling back to the handle rather than overriding with it:
                # a name they chose is the one they will look for in the
                # channel list, and ``@handle`` is only the better default.
                display_name=attempt.display_name.strip() or bot.display_name,
                # Exactly what ``TelegramProvider`` reads and exactly what
                # ``TelegramCredentials`` validates. A channel that connects
                # and then cannot send is the failure this shape prevents.
                credentials={"bot_token": token},
                external_id=str(bot.id),
                # Deliberately absent. The secret is minted by the call that
                # hands it to Telegram, and that call cannot happen yet; a
                # secret written to the column before ``setWebhook`` has
                # accepted it is one no delivery would ever echo.
            ),
        )

    async def register_webhook(
        self, *, callback_url: str, credentials: dict[str, Any], context: DeploymentContext
    ) -> Repair:
        """``setWebhook``, with the URL of a channel that now exists.

        The whole registration lives here, and could not live in ``connect``.
        The ingress route is ``{api_v1_prefix}/webhooks/{channel_config_id}``
        — one URL per channel, keyed by the row's own id, assigned when the
        row is written. ``connect`` used to derive that id as a ``uuid5`` of
        the bot id and register the URL it produced, which no row has ever
        answered: Telegram accepted the registration, ``getWebhookInfo``
        reported a webhook in good order, and every update was delivered to a
        permanent 404. A channel that looked connected and received nothing.

        The secret is minted here for the same reason: it means nothing until
        Telegram has it. It is the entirety of what
        ``TelegramProvider.verify_signature`` has to work with, so it comes
        back as ``Repair.webhook_secret`` — bound for the
        ``ChannelConfig.webhook_secret`` column — and never as a credential.

        Answers rather than raises when Telegram refuses. The row exists by
        now, so a failure here is a saved channel that is not yet delivering
        — something to report and offer a repair for, not an exception thrown
        across a completed write.
        """
        token = _bot_token(credentials)
        if not token:
            return Repair(repaired=False, reason=_ERROR_TOKEN_MISSING)

        secret = secrets.token_urlsafe(_SECRET_BYTES)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            registered = await self._set_webhook(
                client, token=token, url=callback_url, secret=secret
            )
        if not registered:
            # No secret on the way out: Telegram does not have this one, and
            # a column holding a secret nothing echoes fails every inbound
            # signature check exactly as a stale one does.
            return Repair(repaired=False, reason=_ERROR_WEBHOOK_REGISTRATION)
        return Repair(webhook_secret=secret)

    # --- Diagnose -----------------------------------------------------

    async def diagnose(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> DiagnosticReport:
        """What Telegram itself says about this bot, right now.

        Two calls, and between them this connector can answer more of the
        panel than any other in the product — not because it tries harder,
        but because ``getWebhookInfo`` is a provider giving a genuine account
        of its own delivery: whether it holds a webhook for this bot, when it
        last failed to reach it, and how many updates are waiting. Nothing
        else here has an equivalent.

        Every line comes from something Telegram said. Nothing is inferred
        from stored state — that is the platform's half, and it is better at
        it — and nothing is answered optimistically. A fabricated ``OK`` is
        the one thing that makes this panel worse than no panel, because a
        support engineer who cannot trust a green row has to go and read the
        logs anyway, which is the outcome the whole feature exists to avoid.

        What is deliberately not answered, and why:

        - ``PERMISSIONS``: Telegram has no scopes. ``getMe`` returns
          ``can_join_groups`` and ``can_read_all_group_messages``, but those
          are bot *settings*, this connector requires none of them, and
          reporting them against an empty ``required_permissions`` would put
          a row on the panel with nothing to compare against.
        - ``RATE_LIMITS``: the Bot API publishes no headroom — no quota
          headers, nothing on a successful call. It states ``retry_after``
          only while actually throttling, so that is the only time this
          answers, and a permanent green "within limits" would be a
          measurement nobody took.
        - ``LAST_SUCCESSFUL_SYNC``, ``AVERAGE_RESPONSE_TIME``: the provider
          reports neither. Timing our own ``getMe`` would be one sample of
          our own network presented as the provider's latency.
        - ``CONNECTION_HEALTH``: the platform's, from the health sweep that
          already runs. A connector answer wins the merge, so answering here
          would replace a recorded verdict with a single probe.

        Returns findings and never raises, including when the token is
        malformed enough that ``httpx`` refuses to build a URL from it.
        """
        token = _bot_token(credentials)
        if not token:
            # A stored channel with no token cannot be probed at all, and
            # that is itself the finding: nothing about this channel works.
            return self._report(
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.FAIL,
                    detail_key=_DIAG_TOKEN_MISSING,
                )
            )

        try:
            async with httpx.AsyncClient(timeout=_DIAGNOSE_TIMEOUT) as client:
                status, body = await _call(client, token=token, method="getMe")
                items = self._identity(status, body)
                if body.get("ok"):
                    # Only worth asking once the token is known good: every
                    # webhook line would otherwise be reporting the same
                    # rejected credential a second time, in vaguer words.
                    items += await self._delivery(
                        client, token=token, credentials=credentials, context=context
                    )
        except Exception as exc:  # noqa: BLE001 - diagnose returns findings, never raises
            return self._report(
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    # Not FAIL. We did not learn that the credential is bad,
                    # we learned nothing — and a red authentication row sends
                    # a support engineer to reissue a token that was working
                    # fine, during somebody else's outage.
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAG_UNREACHABLE,
                    params={"detail": _redacted(str(exc), credentials, token)},
                )
            )
        return self._report(*items)

    def _report(self, *items: Diagnostic) -> DiagnosticReport:
        """The findings, plus the one line that is true whatever happened."""
        return DiagnosticReport(channel_type=self.channel_type, items=(_API_IS_UNVERSIONED, *items))

    @staticmethod
    def _identity(status: int, body: Mapping[str, Any]) -> list[Diagnostic]:
        """``getMe``, as an authentication verdict.

        The four answers Telegram gives are four different things, and
        collapsing any of them into "the token is bad" would be wrong in a
        way that costs the customer a working credential.
        """
        if status == _TOO_MANY_REQUESTS:
            parameters = body.get("parameters")
            retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
            return [
                Diagnostic(
                    key=DiagnosticKey.RATE_LIMITS,
                    status=DiagnosticStatus.WARN,
                    value=str(retry_after) if isinstance(retry_after, int) else None,
                    detail_key=_DIAG_THROTTLED,
                    params={"unit": "s"},
                ),
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAG_THROTTLED,
                ),
            ]
        if status >= _SERVER_ERROR:
            return [
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAG_UNREACHABLE,
                    params={"status": str(status)},
                )
            ]
        if not body.get("ok"):
            # Telegram rejects a revoked or wrong token as a 401/404 and,
            # occasionally, as a 200 whose body says ``ok: false``. Both mean
            # the same thing, and it is the customer's to fix — in BotFather,
            # since nothing this connector offers can reissue a bot token.
            return [
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.FAIL,
                    detail_key=_DIAG_TOKEN_REJECTED,
                )
            ]
        bot = _bot_from(body.get("result") or {})
        return [
            Diagnostic(
                key=DiagnosticKey.AUTHENTICATION,
                status=DiagnosticStatus.OK,
                # *Which* bot, not just "the token works". The mistake this
                # catches is a staging token on a production channel, which
                # authenticates perfectly and delivers to nobody.
                value=bot.display_name,
                detail_key=_DIAG_AUTHENTICATED,
                params={"username": bot.username, "botId": str(bot.id)},
            )
        ]

    async def _delivery(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        credentials: Mapping[str, Any],
        context: DeploymentContext,
    ) -> list[Diagnostic]:
        """``getWebhookInfo``, as three lines of the panel.

        Silence when Telegram will not answer. An unanswered key comes back
        ``UNKNOWN`` from ``complete()``, which is the truth; a guessed one
        would not be.
        """
        try:
            _status, body = await _call(client, token=token, method="getWebhookInfo")
        except Exception:  # noqa: BLE001 - an unmeasured line is UNKNOWN, not a failure
            return []
        if not body.get("ok"):
            return []
        info = body.get("result") or {}
        if not isinstance(info, dict):
            return []

        url = str(info.get("url") or "")
        items = [self._webhook_status(url, context=context)]
        failure = self._last_failure(info, credentials=credentials, token=token)
        if failure is not None:
            items.append(failure)
        queue = self._retry_queue(info, registered=bool(url))
        if queue is not None:
            items.append(queue)
        return items

    @staticmethod
    def _webhook_status(url: str, *, context: DeploymentContext) -> Diagnostic:
        """Is Telegram pointed at us, at somebody else, or at nothing.

        The third case is the one worth the round trip. A bot has exactly one
        webhook, so any other tool the customer points at the same bot
        silently replaces ours — and from the customer's side that is
        indistinguishable from the bot having stopped working, which is what
        they will report it as.

        Only the host is reported, never the URL. A webhook another tool
        registered may carry that tool's own secret in its path, and this
        report is stored and read by anyone with ``channels.read``.
        """
        if not url:
            return Diagnostic(
                key=DiagnosticKey.WEBHOOK_STATUS,
                status=DiagnosticStatus.FAIL,
                detail_key=_DIAG_WEBHOOK_MISSING,
                repair_action=_REREGISTER_WEBHOOK,
            )
        host = urlsplit(url).netloc
        base = context.public_base_url.rstrip("/")
        # The trailing slash matters: without it
        # ``https://engage.example.com.attacker.test/…`` is a prefix match on
        # this installation's own base URL. And with no base URL to compare
        # against there is no claim to make — a webhook exists, and saying
        # whose it is would be a guess.
        elsewhere = bool(base) and not url.startswith(f"{base}/")
        if not elsewhere:
            return Diagnostic(
                key=DiagnosticKey.WEBHOOK_STATUS,
                status=DiagnosticStatus.OK,
                value=host,
            )
        return Diagnostic(
            key=DiagnosticKey.WEBHOOK_STATUS,
            # A warning rather than a failure: a legitimate second hostname
            # for the same installation looks exactly like this, and blocking
            # somebody's working channel over a DNS change is worse than
            # telling them where their updates are going.
            status=DiagnosticStatus.WARN,
            value=host,
            detail_key=_DIAG_WEBHOOK_ELSEWHERE,
            params={"host": host},
            repair_action=_REREGISTER_WEBHOOK,
        )

    @staticmethod
    def _last_failure(
        info: Mapping[str, Any], *, credentials: Mapping[str, Any], token: str
    ) -> Diagnostic | None:
        """Telegram's own record of the last delivery it could not make.

        Reported only when there is one. Telegram's silence means "no
        delivery to this webhook has ever failed", which is *not* the same
        statement as this key's — the platform answers it from the connection
        log, where a failed outbound send is also a failed request. A
        connector answer wins the merge, so returning a cheerful "nothing
        failed" here would erase a real failure the platform had recorded.
        """
        failed_at = _moment(info.get("last_error_date"))
        message = info.get("last_error_message")
        if failed_at is None or not message:
            return None
        return Diagnostic(
            key=DiagnosticKey.LAST_FAILED_REQUEST,
            status=DiagnosticStatus.WARN,
            value=failed_at.isoformat(),
            detail_key=_DIAG_DELIVERY_FAILURE,
            # Telegram's text describes what it could not reach — routinely
            # our own URL, and on a bot somebody else has registered, theirs.
            # Through the sanitiser like every other provider string.
            params={"detail": _redacted(str(message), credentials, token)},
            measured_at=failed_at,
            repair_action=_REREGISTER_WEBHOOK,
        )

    @staticmethod
    def _retry_queue(info: Mapping[str, Any], *, registered: bool) -> Diagnostic | None:
        """How many updates Telegram is holding for this bot.

        The number that makes "the bot has stopped answering" legible. With
        no webhook registered, Telegram queues updates for the bot and
        nothing ever drains them — the failure ``configure_webhook`` exists
        to prevent, and the one an operator has no other way of seeing.
        """
        pending = info.get("pending_update_count")
        if not isinstance(pending, int) or isinstance(pending, bool) or pending < 0:
            return None
        if pending == 0:
            return Diagnostic(
                key=DiagnosticKey.RETRY_QUEUE,
                status=DiagnosticStatus.OK,
                value="0",
            )
        if not registered:
            return Diagnostic(
                key=DiagnosticKey.RETRY_QUEUE,
                status=DiagnosticStatus.WARN,
                value=str(pending),
                detail_key=_DIAG_PENDING_UNDELIVERABLE,
                repair_action=_REREGISTER_WEBHOOK,
            )
        if pending < _PENDING_UPDATE_BACKLOG:
            # In flight, not stuck. Reported as the measurement it is.
            return Diagnostic(
                key=DiagnosticKey.RETRY_QUEUE,
                status=DiagnosticStatus.OK,
                value=str(pending),
            )
        return Diagnostic(
            key=DiagnosticKey.RETRY_QUEUE,
            status=DiagnosticStatus.WARN,
            value=str(pending),
            detail_key=_DIAG_PENDING_UPDATES,
            repair_action=_REREGISTER_WEBHOOK,
        )

    # --- Certify ------------------------------------------------------

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
        """Demonstrate one behaviour against the real Bot API.

        Nothing here decides whether a scenario applies or whether it is safe
        to run: the runner has already reported ``NOT_SUPPORTED`` for anything
        this manifest never claimed, and ``SKIPPED`` for anything that would
        message a person without a target or change the channel without an
        opt-in. Being called means being expected to try, so the only reasons
        a scenario comes back unexecuted from here are reasons Telegram gave.

        Three outcomes, and the line between the last two is the whole value
        of the report:

        - ``PASS``/``WARNING`` — Telegram did the thing, and said so.
        - ``FAIL`` — Telegram was asked and refused. The channel is broken.
        - ``SKIPPED`` — nobody was able to ask. A provider outage, a throttle,
          a precondition the run does not hold. It costs coverage rather than
          score, because an unexecuted test is an unanswered question.

        Never raises, and never returns ``PASS`` for anything it did not
        watch happen.
        """
        token = _bot_token(credentials)
        if not token:
            # Nothing can be attempted at all. Not a failure of this scenario
            # — it never started — and the AUTHENTICATION row carries the same
            # fact in the place an operator looks first.
            return _outcome(kind, Outcome.SKIPPED, _CERT_TOKEN_MISSING)

        try:
            match kind:
                case ScenarioKind.AUTHENTICATION:
                    return await self._prove_identity(kind, token=token, credentials=credentials)
                case ScenarioKind.WEBHOOK_DELIVERY:
                    return await self._prove_delivery(
                        kind, token=token, credentials=credentials, context=context
                    )
                case ScenarioKind.RECEIVE_MESSAGE:
                    return self._prove_receiving(kind)
                case ScenarioKind.SEND_MESSAGE:
                    return await self._prove_sending(
                        kind, token=token, credentials=credentials, target=target
                    )
                case ScenarioKind.MEDIA_UPLOAD:
                    return await self._prove_upload(
                        kind, token=token, credentials=credentials, target=target
                    )
                case ScenarioKind.TYPING_INDICATOR:
                    return await self._prove_typing(
                        kind, token=token, credentials=credentials, target=target
                    )
                case ScenarioKind.MEDIA_DOWNLOAD:
                    return await self._prove_download(
                        kind, token=token, credentials=credentials, target=target
                    )
                case ScenarioKind.TOKEN_REFRESH:
                    return self._prove_token_refresh(kind)
                case ScenarioKind.DISCONNECT | ScenarioKind.RECONNECT:
                    return self._prove_reconnection(kind)
                case _:
                    # Unreachable through the runner: ``READ_RECEIPT`` is the
                    # only kind left, this manifest does not claim
                    # ``READ_RECEIPTS``, and a scenario the manifest never
                    # claimed is reported ``NOT_SUPPORTED`` before we are
                    # called. Answered rather than asserted, because a caller
                    # that is not the runner must still get a result.
                    return _outcome(kind, Outcome.SKIPPED, "certification.notImplemented")
        except Exception as exc:  # noqa: BLE001 - a scenario reports, it never raises
            # Everything Telegram can do to us is already an outcome above, so
            # anything arriving here is a defect in this connector. Reported
            # as ``FAIL`` — the same score the runner would give the raise
            # this replaces, and never as ``SKIPPED``, which would let a bug
            # buy its way out of the denominator.
            return _outcome(
                kind,
                Outcome.FAIL,
                _CERT_UNEXPECTED,
                diagnostics={"error": _redacted(str(exc), credentials, token)},
            )

    async def _prove_identity(
        self, kind: ScenarioKind, *, token: str, credentials: Mapping[str, Any]
    ) -> ScenarioResult:
        """``getMe``, judged by the same function ``diagnose`` judges it with.

        The call is repeated; the *verdict* is not. ``_identity`` is the one
        place that decides what each of Telegram's four answers means, and a
        second opinion here would eventually disagree with the diagnostics
        panel — a channel certified green beside a red authentication row,
        with nothing to say which was right.

        ``UNKNOWN`` becomes ``SKIPPED`` rather than ``FAIL`` for the reason
        ``diagnose`` gives it: we did not learn that the credential is bad, we
        learned nothing, and a red row sends a support engineer to reissue a
        working token during somebody else's outage.
        """
        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            answer = await _ask(client, token=token, credentials=credentials, method="getMe")

        unmeasured = _unmeasured(kind, answer)
        if unmeasured is not None:
            return unmeasured

        verdicts = self._identity(answer.status, answer.body)
        authentication = next(
            (item for item in verdicts if item.key is DiagnosticKey.AUTHENTICATION), None
        )
        if authentication is None:  # pragma: no cover - ``_identity`` always answers this key
            return _outcome(kind, Outcome.SKIPPED, _CERT_NOT_MEASURED)

        if authentication.status is DiagnosticStatus.OK:
            # *Which* bot, not merely that a token worked. The mistake this
            # catches is a staging token on a production channel, which
            # authenticates perfectly and delivers to nobody.
            return _outcome(
                kind,
                Outcome.PASS,
                _CERT_AUTHENTICATED,
                params={"botName": authentication.value or ""},
                diagnostics={
                    "username": authentication.params.get("username", ""),
                    "bot_id": authentication.params.get("botId", ""),
                },
            )
        if authentication.status is DiagnosticStatus.FAIL:
            return _outcome(
                kind,
                Outcome.FAIL,
                authentication.detail_key or _CERT_TOKEN_NOT_ACCEPTED,
                diagnostics={
                    "status": str(answer.status),
                    "description": _redacted(answer.description, credentials, token),
                },
            )
        if authentication.status is DiagnosticStatus.WARN:
            return _outcome(kind, Outcome.WARNING, authentication.detail_key or _CERT_AUTHENTICATED)
        return _outcome(kind, Outcome.SKIPPED, authentication.detail_key or _CERT_NOT_MEASURED)

    async def _prove_delivery(
        self,
        kind: ScenarioKind,
        *,
        token: str,
        credentials: Mapping[str, Any],
        context: DeploymentContext,
    ) -> ScenarioResult:
        """``getWebhookInfo`` — Telegram's own account of whether it reaches us.

        The one scenario in the product where the provider genuinely reports
        on itself, and the reason this connector can certify delivery at all
        while others can only certify that a URL was configured somewhere.

        Read through the same three classifiers the diagnostics panel uses, so
        the certification row and the panel cannot tell an operator different
        things about one ``getWebhookInfo`` response:

        - no URL at all — Telegram has nowhere to deliver and updates are
          piling up behind it. ``FAIL``; this is a channel that receives
          nothing, whatever else works.
        - a URL on somebody else's host — ``WARNING``, not ``FAIL``, because a
          second legitimate hostname for this installation looks identical to
          a bot another tool has taken over, and only one of those is broken.
        - a recent delivery failure, or a queue nobody is draining —
          ``WARNING`` carrying what Telegram said.
        - otherwise ``PASS``.

        A failure Telegram recorded weeks ago does not warn: it is kept as
        evidence and nothing more. Telegram never reports a delivery it
        *managed*, so an old error behind an empty queue is the only shape
        "this recovered" can take, and warning about it forever would train an
        operator to ignore the row that eventually matters.
        """
        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            answer = await _ask(
                client, token=token, credentials=credentials, method="getWebhookInfo"
            )

        unmeasured = _unmeasured(kind, answer)
        if unmeasured is not None:
            return unmeasured
        if not answer.ok:
            # A rejected token, almost always. Delivery was not measured, and
            # the AUTHENTICATION row already fails for it — counting one dead
            # credential as two broken behaviours would make the score say
            # something arithmetically true and factually misleading.
            return _outcome(
                kind,
                Outcome.SKIPPED,
                _CERT_NOT_MEASURED,
                diagnostics={
                    "status": str(answer.status),
                    "description": _redacted(answer.description, credentials, token),
                },
            )

        info = answer.result
        url = str(info.get("url") or "")
        registration = self._webhook_status(url, context=context)
        failure = self._last_failure(info, credentials=credentials, token=token)
        queue = self._retry_queue(info, registered=bool(url))

        evidence = {
            "webhook_host": registration.value or "",
            "pending_updates": (queue.value or "") if queue is not None else "",
            "last_error_at": (failure.value or "") if failure is not None else "",
            "last_error": failure.params.get("detail", "") if failure is not None else "",
        }

        if registration.status is DiagnosticStatus.FAIL:
            return _outcome(kind, Outcome.FAIL, _CERT_WEBHOOK_MISSING, diagnostics=evidence)
        if registration.status is DiagnosticStatus.WARN:
            return _outcome(
                kind,
                Outcome.WARNING,
                _CERT_WEBHOOK_ELSEWHERE,
                params={"host": registration.value or ""},
                diagnostics=evidence,
            )
        if failure is not None and _recent(failure.measured_at):
            return _outcome(
                kind,
                Outcome.WARNING,
                _CERT_WEBHOOK_FAILING,
                params={"detail": failure.params.get("detail", ""), "at": failure.value or ""},
                diagnostics=evidence,
            )
        if queue is not None and queue.status is DiagnosticStatus.WARN:
            return _outcome(
                kind,
                Outcome.WARNING,
                _CERT_WEBHOOK_BACKLOG,
                params={"pending": queue.value or ""},
                diagnostics=evidence,
            )
        return _outcome(
            kind,
            Outcome.PASS,
            _CERT_WEBHOOK_REGISTERED,
            params={"host": registration.value or ""},
            diagnostics=evidence,
        )

    @staticmethod
    def _prove_receiving(kind: ScenarioKind) -> ScenarioResult:
        """``SKIPPED``, and the one place this connector was owed a ``PASS``.

        The evidence is genuinely tempting: a registered webhook pointing at
        this installation, no delivery failure, ``pending_update_count`` at
        zero. It reads like a bot receiving messages, and calling it one would
        give Telegram a scenario nobody else in the product can execute.

        It is the wrong measurement, twice over.

        It is not evidence of receiving. Telegram holding a delivery address
        is a statement about Telegram, not about us: zero pending updates is
        equally the signature of a channel nobody has ever messaged, and a
        queue that is empty because there was never anything in it looks
        exactly like a queue that is empty because everything drained. Neither
        does any of it exercise the half that actually breaks — an update
        arriving at our endpoint, clearing signature verification, and
        ``receive_message`` turning it into a ``Message`` row. A bot with a
        perfect ``getWebhookInfo`` and a stale ``webhook_secret`` discards
        every update it is sent, silently, and would certify green here.

        And it is a measurement this report already contains. It is precisely
        what ``WEBHOOK_DELIVERY`` asserts, reported one row above; counting it
        again under a second name would be one fact presented as two, which is
        how a coverage number stops meaning anything.

        Receiving needs a customer to send something, and nothing in a
        certification run may cause that. So this stays unexecuted and says
        why — which costs coverage, and should.
        """
        return _outcome(kind, Outcome.SKIPPED, _CERT_INBOUND_NOT_PROVOKABLE)

    async def _prove_sending(
        self,
        kind: ScenarioKind,
        *,
        token: str,
        credentials: Mapping[str, Any],
        target: str | None,
    ) -> ScenarioResult:
        """``sendMessage`` to the chat somebody named on purpose."""
        if not target:
            # Not a second guess at the runner's safety gate — that one is
            # about consent, and it already ran. This is the mechanical half:
            # there is no chat to name in the payload, and it is what makes
            # "this never sends without a target" true of the method rather
            # than of its caller.
            return _outcome(kind, Outcome.SKIPPED, _CERT_NO_TARGET_CHAT)

        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            answer = await _ask(
                client,
                token=token,
                credentials=credentials,
                method="sendMessage",
                payload={"chat_id": target, "text": _CERTIFICATION_MESSAGE},
            )

        unmeasured = _unmeasured(kind, answer)
        if unmeasured is not None:
            return unmeasured
        if not answer.ok:
            return _rejected(kind, answer, credentials=credentials, token=token)
        message_id = _sent_id(answer.result)
        if not message_id:
            # Telegram said ok and named nothing. A pass with no provider id
            # behind it is a pass nobody can check against a real Message row,
            # and `_outcome` drops empty evidence — so it would be
            # indistinguishable from one that carried it. Both siblings guard
            # this: SMS skips an empty sid, Meta warns on one.
            return _outcome(kind, Outcome.WARNING, _CERT_MESSAGE_UNCONFIRMED)
        return _outcome(
            kind,
            Outcome.PASS,
            _CERT_MESSAGE_SENT,
            diagnostics={"message_id": message_id, "status": str(answer.status)},
        )

    async def _prove_upload(
        self,
        kind: ScenarioKind,
        *,
        token: str,
        credentials: Mapping[str, Any],
        target: str | None,
    ) -> ScenarioResult:
        """``sendPhoto``, with real bytes, by the route the provider uses.

        Multipart with the image inline rather than a URL Telegram would fetch
        for us: the second proves Telegram's downloader works, and it is the
        first that ``TelegramProvider._send_attachments`` actually does.

        The file id in the evidence is the part worth keeping. Telegram issues
        one only once it holds the bytes, so it is the difference between "the
        request was accepted" and "the upload landed".
        """
        if not target:
            return _outcome(kind, Outcome.SKIPPED, _CERT_NO_TARGET_CHAT)

        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            answer = await _ask(
                client,
                token=token,
                credentials=credentials,
                method="sendPhoto",
                payload={"chat_id": target, "caption": _CERTIFICATION_MESSAGE},
                files={
                    "photo": (_CERTIFICATION_IMAGE_NAME, _CERTIFICATION_IMAGE, "image/png"),
                },
            )

        unmeasured = _unmeasured(kind, answer)
        if unmeasured is not None:
            return unmeasured
        if not answer.ok:
            return _rejected(kind, answer, credentials=credentials, token=token)
        file_id = _largest_photo_file_id(answer.result)
        if not file_id:
            # The docstring's own claim, now enforced: Telegram issues a
            # file id only once it holds the bytes, which is the difference
            # between "the request was accepted" and "the upload landed".
            # Passing without one asserted the second and measured the first.
            return _outcome(kind, Outcome.WARNING, _CERT_PHOTO_UNCONFIRMED)
        return _outcome(
            kind,
            Outcome.PASS,
            _CERT_PHOTO_SENT,
            diagnostics={
                "message_id": _sent_id(answer.result),
                "file_id": file_id,
                "bytes_sent": str(len(_CERTIFICATION_IMAGE)),
            },
        )

    async def _prove_typing(
        self,
        kind: ScenarioKind,
        *,
        token: str,
        credentials: Mapping[str, Any],
        target: str | None,
    ) -> ScenarioResult:
        """``sendChatAction``, and the honest limit of what it proves.

        Telegram answers ``result: true`` and nothing else — no id, no handle,
        and no update that would let a bot observe its own indicator. So a
        ``PASS`` here means Telegram accepted a typing action for this chat,
        which is the whole of what the Bot API offers to measure. Saying more
        would be describing a bubble nobody here can see.
        """
        if not target:
            return _outcome(kind, Outcome.SKIPPED, _CERT_NO_TARGET_CHAT)

        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            answer = await _ask(
                client,
                token=token,
                credentials=credentials,
                method="sendChatAction",
                payload={"chat_id": target, "action": "typing"},
            )

        unmeasured = _unmeasured(kind, answer)
        if unmeasured is not None:
            return unmeasured
        if not answer.ok:
            return _rejected(kind, answer, credentials=credentials, token=token)
        return _outcome(
            kind,
            Outcome.PASS,
            _CERT_TYPING_ACCEPTED,
            diagnostics={"action": "typing", "status": str(answer.status)},
        )

    async def _prove_download(
        self,
        kind: ScenarioKind,
        *,
        token: str,
        credentials: Mapping[str, Any],
        target: str | None,
    ) -> ScenarioResult:
        """``getFile`` and the file service, against the target chat's photo.

        Downloading needs a file id, and a file id normally arrives on an
        inbound message this run cannot cause. Two files are reachable without
        waiting for a customer — the target chat's photo, or, when the target
        is a one-to-one chat, the profile photo of the person on the other end
        — and both are pulled down through exactly the two steps
        ``TelegramProvider._download_file`` takes: ``getFile`` for the path,
        then the bytes from the file service. What that does *not* exercise is
        pulling a file id out of an update, which is the half that needs a
        human and the half ``RECEIVE_MESSAGE`` declines to claim.

        Nothing is sent to get there. ``MEDIA_DOWNLOAD`` is deliberately not
        one of the scenarios the runner gates on a target, because downloading
        observes and does not emit — and the obvious way to guarantee a file
        to fetch, uploading one first, would quietly turn a read-only scenario
        into one that messages somebody.

        The line between ``SKIPPED`` and ``FAIL`` here is precise: not being
        able to obtain a file id is a missing precondition, and every reason
        for it (no target, a chat this bot cannot see, a chat with no photo)
        is a fact about the run rather than about the download path. Once
        Telegram has handed us an id it issued itself, anything that goes
        wrong after that is the download path failing.
        """
        if not target:
            return _outcome(kind, Outcome.SKIPPED, _CERT_NO_TARGET_CHAT)

        async with httpx.AsyncClient(timeout=_SCENARIO_TIMEOUT) as client:
            chat = await _ask(
                client,
                token=token,
                credentials=credentials,
                method="getChat",
                payload={"chat_id": target},
            )
            unmeasured = _unmeasured(kind, chat)
            if unmeasured is not None:
                return unmeasured

            file_id = _chat_photo_file_id(chat.result) if chat.ok else ""
            user_id = _private_chat_user_id(chat.result) if chat.ok else None
            if not file_id and user_id is not None:
                # A one-to-one chat has no photo of its own — the participants
                # do. Worth the extra round trip because a private chat is
                # what an operator names as a test target nine times in ten,
                # and without it this scenario almost never runs.
                photos = await _ask(
                    client,
                    token=token,
                    credentials=credentials,
                    method="getUserProfilePhotos",
                    payload={"user_id": user_id, "limit": 1},
                )
                unmeasured = _unmeasured(kind, photos)
                if unmeasured is not None:
                    return unmeasured
                file_id = _profile_photo_file_id(photos.result) if photos.ok else ""

            if not file_id:
                return _outcome(
                    kind,
                    Outcome.SKIPPED,
                    _CERT_NO_FILE_TO_DOWNLOAD,
                    diagnostics={
                        "description": _redacted(chat.description, credentials, token),
                    },
                )

            located = await _ask(
                client,
                token=token,
                credentials=credentials,
                method="getFile",
                payload={"file_id": file_id},
            )
            unmeasured = _unmeasured(kind, located)
            if unmeasured is not None:
                return unmeasured
            if not located.ok:
                return _rejected(kind, located, credentials=credentials, token=token)

            file_path = str(located.result.get("file_path") or "")
            if not file_path:
                # ``getFile`` succeeded and named nothing to fetch. Telegram
                # promises a path on a resolvable id, so this is the download
                # path not working rather than a precondition we lack.
                return _outcome(
                    kind, Outcome.FAIL, _CERT_REJECTED, diagnostics={"status": str(located.status)}
                )

            fetched = await _fetch_file(
                client, token=token, credentials=credentials, file_path=file_path
            )

        if fetched.error is not None:
            return _outcome(
                kind, Outcome.SKIPPED, _CERT_UNREACHABLE, diagnostics={"error": fetched.error}
            )
        if fetched.status >= _SERVER_ERROR:
            return _outcome(
                kind,
                Outcome.SKIPPED,
                _CERT_UNREACHABLE,
                diagnostics={"status": str(fetched.status)},
            )
        if fetched.status != _OK or fetched.size <= 0:
            # An id Telegram issued, a path Telegram named, and no bytes at
            # the end of it. Nothing about that is a missing precondition.
            return _outcome(
                kind,
                Outcome.FAIL,
                _CERT_REJECTED,
                diagnostics={
                    "status": str(fetched.status),
                    "bytes_received": str(fetched.size),
                },
            )
        return _outcome(
            kind,
            Outcome.PASS,
            _CERT_FILE_DOWNLOADED,
            # The path, not the URL: the URL it hangs off carries the bot
            # token, and this report is read by anyone with ``channels.read``.
            diagnostics={"file_path": file_path, "bytes_received": str(fetched.size)},
        )

    @staticmethod
    def _prove_token_refresh(kind: ScenarioKind) -> ScenarioResult:
        """There is nothing to refresh, and saying so is not the same as passing.

        Bot tokens do not expire. They are revoked — deliberately, by the
        customer, in BotFather — which is why ``TOKEN_REFRESH`` is absent from
        this manifest's capabilities and why no refresh material is stored.

        Reported as ``SKIPPED`` rather than ``NOT_SUPPORTED``, which was
        available and is the wrong answer coming from here: ``NOT_SUPPORTED``
        removes the row from the denominator entirely, and a connector that
        can strike its own scenarios off the list is a connector setting its
        own score. That judgement is the runner's, from the manifest. So this
        costs coverage instead, which is the correct price for a question this
        run did not answer.
        """
        return _outcome(kind, Outcome.SKIPPED, _CERT_TOKENS_DO_NOT_EXPIRE)

    @staticmethod
    def _prove_reconnection(kind: ScenarioKind) -> ScenarioResult:
        """The two scenarios that are one API call each, and still cannot run.

        ``deleteWebhook`` and ``setWebhook`` are trivially callable here, the
        operator has opted into mutation by asking for it, and either would
        return ``ok: true`` within the second. That is what makes this the
        most dangerous ``PASS`` available in this file.

        Telegram holds ``secret_token`` write-only. ``getWebhookInfo`` reports
        the URL, the last error and the queue, and never the secret — so a
        webhook that is torn down cannot be put back as it was, only replaced
        with one carrying a *new* secret. A scenario has nowhere to return
        that: ``register_webhook`` and ``repair`` hand theirs back as
        ``Repair.webhook_secret``, bound for the ``ChannelConfig`` column, and
        ``run_scenario`` returns a ``ScenarioResult``, whose ``diagnostics``
        are read by anyone with ``channels.read`` and are the last place a live
        secret should be written.

        So the channel would come back looking perfect — a URL registered, no
        error, an empty queue — while ``TelegramProvider.verify_signature``
        rejected every update against a column Telegram no longer agrees with.
        Silently, because a channel nobody has messaged looks exactly the same.
        A certification run that produced that state would have caused, in the
        name of measuring it, the precise failure it exists to catch.

        The honest report is two unexecuted rows and the reason. What would
        make them executable is not a connector change: it is
        ``run_scenario`` being given the callback URL and stored secret the
        repair path already receives, or a way to hand a rotated secret back.
        Until then, the button that genuinely re-registers this webhook is the
        ``reregister_webhook`` repair, which has both.
        """
        return _outcome(kind, Outcome.SKIPPED, _CERT_SECRET_NOT_RECOVERABLE)

    # ``supported_until`` is deliberately not overridden. The base returns
    # ``None`` and that is the true answer here: the Bot API states no version
    # anywhere — see ``versions.api="unversioned"`` above — so there is nothing
    # to retire and no schedule to read a date off. An administrator plans a
    # migration around that field, and a plausible-looking date invented to
    # fill the row would manufacture the deprecation risk the field exists to
    # report.

    # --- Repair -------------------------------------------------------

    async def repair(
        self,
        *,
        action: str,
        credentials: dict[str, Any],
        webhook_secret: str | None = None,
        callback_url: str | None = None,
        context: DeploymentContext,
    ) -> Repair:
        """Put the webhook back.

        Worth a button because Telegram takes webhooks away without being
        asked: it drops a registration after a long enough run of failed
        deliveries, and any other tool the customer points at the same bot
        replaces ours outright, since a bot has exactly one webhook. Both
        look identical from the customer's side — the bot simply stops
        answering — and both are fixed by the same call.

        Both of the values that made the old version wrong now arrive from
        the caller. The secret was read from ``credentials["webhook_secret"]``
        — a key nothing writes — so every press minted a fresh one and
        returned it under a credentials key nothing reads: Telegram then
        signed its updates with a secret the stored column did not have, and
        every inbound message was discarded as unverifiable, silently,
        because a channel nobody has messaged looks the same. It is now the
        column's own value, reused, and returned as ``Repair.webhook_secret``
        so a caller that persists it puts it back where it came from.

        A fresh one is minted only when there is nothing to reuse. Calling
        ``setWebhook`` without any ``secret_token`` would be worse than the
        bug it replaces: Telegram accepts it, clears the secret, and the URL
        becomes something anyone who guesses it can post updates to.

        The URL is the caller's too. Reproducing it here would mean deriving
        a channel id from the bot again, which is the fabrication that made
        the original registration a 404.
        """
        if action != _REREGISTER_WEBHOOK:
            return Repair(repaired=False, reason=_REASON_NOT_SUPPORTED)

        token = _bot_token(credentials)
        if not token:
            return Repair(repaired=False, reason=_ERROR_TOKEN_MISSING)
        if not callback_url:
            return Repair(repaired=False, reason=_ERROR_CALLBACK_URL_MISSING)

        secret = webhook_secret or secrets.token_urlsafe(_SECRET_BYTES)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            registered = await self._set_webhook(
                client, token=token, url=callback_url, secret=secret
            )
        if not registered:
            return Repair(repaired=False, reason=_ERROR_WEBHOOK_REGISTRATION)
        # ``credentials`` stays ``None``: this repair changed the webhook, not
        # the token. Echoing the credentials back unchanged would ask the
        # caller to re-encrypt and rewrite a column for nothing, and would
        # make a repair that genuinely rotates a credential indistinguishable
        # from one that did not.
        return Repair(webhook_secret=secret)

    # --- Bot API ------------------------------------------------------

    async def _identify(self, client: httpx.AsyncClient, *, token: str) -> _Bot:
        try:
            _status, body = await _call(client, token=token, method="getMe")
        except Exception as exc:
            raise TelegramSetupError(_ERROR_TOKEN_REJECTED) from exc
        if not body.get("ok"):
            raise TelegramSetupError(_ERROR_TOKEN_REJECTED)
        return _bot_from(body.get("result") or {})

    async def _set_webhook(
        self, client: httpx.AsyncClient, *, token: str, url: str, secret: str
    ) -> bool:
        """The same call ``TelegramProvider.configure_webhook`` makes.

        Answers whether Telegram accepted it, rather than raising. Both
        callers run after the channel row exists and both return a ``Repair``
        — the same treatment ``ChannelConfigService`` already gives a failed
        registration on a saved channel, where the failure belongs in the
        connection log rather than in an exception unwinding a completed
        write. What the customer is owed is the knowledge that the bot is not
        receiving yet, and a button; not a traceback.
        """
        try:
            _status, body = await _call(
                client,
                token=token,
                method="setWebhook",
                payload={"url": url, "secret_token": secret},
            )
        except Exception:  # noqa: BLE001 - every path out of here is a Repair
            # Same breadth as ``check``: a token with a newline in it makes
            # httpx raise ``InvalidURL`` before a request is ever attempted,
            # and that is not an ``HTTPError``.
            return False
        return bool(body.get("ok"))


__all__ = ["TelegramConnector", "TelegramSetupError"]
