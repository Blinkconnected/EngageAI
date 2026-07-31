"""SMS — one channel, several carriers, and a form that has to admit it.

Every other connector in this package speaks to exactly one vendor: there is
one WhatsApp, one Telegram. SMS is a medium, not a vendor. Twilio, Vonage,
MessageBird and Plivo are different APIs for the same message, which is why
the transport layer already carries a second plugin level — ``SmsProvider``
delegates to whichever ``SmsGateway`` its ``credentials["gateway"]`` names
(``docs/architecture/sms.md``). The connection flow inherits that shape: the
first thing to establish is not a credential but whose credentials are about
to be typed.

That choice is a ``select`` on the credentials form rather than a step of its
own, and the form carries the *union* of every registered gateway's fields.
The alternative — branch the wizard per gateway — is the same mistake this
package exists to prevent, one level down: the console would be asking "which
gateway is this?" exactly as it used to ask "which channel is this?", and
every new carrier would be a frontend change. ``StepId`` has one AUTHENTICATE
stage and ``StepKind`` one form renderer, and neither should grow a variant
because SMS is shaped differently from Telegram. The price is paid honestly
rather than hidden: a field is ``required`` only when *every* selectable
gateway needs it, so with one carrier compiled in the form is exactly as
strict as a per-carrier form would be, and with three it relaxes to what they
agree on while ``check`` and ``connect`` enforce the remainder against the
carrier actually chosen. A form that refused to submit until a Vonage
customer produced a Twilio account SID would be far worse than one that shows
the field and says who it is for.

No OAuth, and no ``app_key``. Carrier credentials are an account identifier
and an auth token minted in the carrier's own console; none of these vendors
offers a consent screen for their messaging API, so there is no platform app
to hold and nothing here that differs between a hosted installation and a
self-hosted one. What does differ is the build, which is why ``resolve`` is
overridden: with no gateway registered that this connector can collect
credentials for, every capability is reported unavailable, because a channel
that cannot name a carrier is a dead end and the picker should not offer one.

``AUTO_DISCOVERY`` is deliberately absent even though the enumeration exists.
A Twilio account does list its phone numbers, and this connector does fetch
them — but ``steps_for`` renders a picker only for a customer who consented,
on the sound reasoning that a pasted credential has already named the
resource. It has: the sending number is a field on the form. So the account's
number list is spent where it changes an outcome instead, as a Permissions
Check that catches the number belonging to a different account, or bought
voice-only — the two ways an SMS channel connects cleanly and then silently
fails to send.

``WEBHOOKS`` yes, and — now — ``AUTOMATIC_WEBHOOK_REGISTRATION``. The
capability was refused here once, and the reason was never a missing API:
Twilio will set a number's ``SmsUrl`` over REST. It was an ordering problem.
The callback URL contains the channel's own id, which is assigned when the
``Connection`` returned from ``connect`` is persisted, so at the only moment
``connect`` could have registered anything there was no URL to register, and
a connector that registers an invented id points a carrier at a route that
answers 404 until somebody notices. ``register_webhook`` runs afterwards and
is handed the real URL, which is precisely what turns a capability that could
only ever half-work into one this connector can declare honestly. What
survives of the old warning is now per *carrier* rather than per channel: a
gateway whose entry here has no registration hook still tells the customer at
VERIFY that one paste into a console remains, and still says it as a warning
rather than a failure, because outbound works the instant the credentials do
and only inbound waits on it. ``SHARED_WEBHOOK`` is absent for the ordinary
reason: each channel has its own ingress URL, and nothing about a carrier's
account model fans several tenants into one.

The URL is registered byte for byte as given. ``TwilioGateway.verify_signature``
recomputes its HMAC over the URL Twilio requested, and the ingress route
rebuilds that URL from ``public_base_url`` plus the request path — so a
callback "tidied" here with a trailing slash or an extra query parameter would
authenticate every send and then fail the signature on every delivery, which
is the same silent-inbound failure by a different route.

``webhook_secret`` is ``None`` on purpose, from ``connect`` and from every
``Repair`` this file returns. Twilio signs its deliveries with the same auth
token that authorises sends, and ``TwilioGateway`` verifies against exactly
that — the relationship ``PROVIDER_SIGNED_CHANNELS`` records for the Meta
family. Generating a random secret here would reproduce the failure described
there: a channel that connects green and then discards every inbound message,
which is not a symptom anyone can diagnose.

Every fix this file offers is ``reenter`` or ``manual``, and never
``reauthorize``. There is no consent screen behind any of these carriers, so
a reauthorize fix renders a button that goes nowhere — the reason the fix kind
exists at all. For a channel authenticated by pasting a secret, a mistyped
credential is *the* commonest failure and the fix is one step back to the form
the customer just left.

Nothing here reads ``Attempt.grant``. With no consent step there is nothing to
put in it, so ``Attempt.credentials`` resolves to what the customer typed, and
reading the property rather than either dict is what keeps this file
indifferent to which step produced the values — the distinction the first
version of the contract blurred, and the one every connector guessed at
differently.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

# Registers the gateways this connector is allowed to offer. Imported for the
# same reason SmsProvider imports it: the select must reflect what this build
# can actually send with, not what this file happens to describe.
import blinkengage.infrastructure.channels.gateways  # noqa: F401
from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    DeploymentContext,
    Repair,
)
from blinkengage.domain.connector_manifest import (
    AuthMethod,
    ConnectorCategory,
    ConnectorManifest,
    CredentialSpec,
    RepairAction,
    ValidationCode,
    ValidationResult,
    VerificationSpec,
)
from blinkengage.domain.connectors import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    Capability,
    CapabilityState,
    ConnectorProfile,
)
from blinkengage.domain.exceptions import (
    InvalidChannelCredentialsError,
    InvalidSmsGatewayError,
)
from blinkengage.infrastructure.channels.error_sanitizer import redact_credentials
from blinkengage.infrastructure.channels.sms_gateway_registry import SmsGatewayRegistry
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: The credentials key ``SmsProvider`` reads to pick a gateway. It is part of
#: the stored credentials rather than a column because the transport layer
#: looks it up by name from a database-stored string, exactly as the outer
#: registry does for channel types.
_GATEWAY_FIELD = "gateway"

#: Reported when the build carries no gateway this connector can configure.
#: A code in the shape ``Connector.resolve`` already uses, not a sentence.
_NO_GATEWAY = "no_sms_gateway_available"

#: Reported when carriers are configurable but none of them can be pointed at
#: a callback URL from here. Separate from ``_NO_GATEWAY`` because the channel
#: is perfectly connectable in that state — only the promise of automatic
#: inbound setup is not on offer.
_NO_WEBHOOK_REGISTRATION = "no_sms_gateway_registers_webhooks"

#: Long enough that a carrier's ordinary latency is not read as an outage,
#: short enough that a wizard step does not appear to hang. Explicit because
#: httpx's default would let a black-holed connection stall the checklist.
_PROBE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

#: The statuses that mean the carrier looked at our credentials and refused
#: them, rather than having a problem of its own — the same split, and the
#: same three codes, ``error_sanitizer.classify_health_check_failure`` uses to
#: decide whose fault an unhealthy channel is. Read only against the call that
#: authenticates; see ``_number_unverified``.
_REJECTED_STATUS_CODES = frozenset({401, 403, 404})

_TWILIO_API = "https://api.twilio.com/2010-04-01"

#: The one repair this connector offers, named in the health states that
#: produce it and answered by ``repair``.
_REREGISTER_WEBHOOK = "reregister_webhook"

#: Details on the exceptions this connector raises and reasons on the repairs
#: it returns. Keys, not sentences, for the reason every check code is one:
#: a detail composed on the server reaches the customer through the API and
#: can only ever be English. ``docs/architecture/billing.md`` records the same
#: decision for status codes.
_ERROR_CREDENTIAL_MISSING = "connect.sms.error.credentialMissing"
_ERROR_GATEWAY_UNKNOWN = "connect.sms.error.gatewayUnknown"
_ERROR_NUMBER_NOT_ON_ACCOUNT = "connect.sms.error.numberNotOnAccount"
_ERROR_WEBHOOK_REGISTRATION = "connect.sms.error.webhookRegistrationFailed"
_ERROR_NO_CALLBACK_URL = "connect.sms.error.callbackUrlMissing"

#: The contract's own code for "this is not something I do", returned verbatim
#: rather than translated into a key of this module's own, so a caller can
#: tell a carrier that has no registration API from one that tried and failed.
_NOT_SUPPORTED = "not_supported"


def _text(values: Mapping[str, Any], name: str) -> str:
    """A trimmed string for a value a customer pasted.

    Credentials arrive from a form and from clipboards, and a trailing
    newline in an account identifier is the difference between a request and
    an ``httpx.InvalidURL`` — the exact breakage ``safe_health_check`` exists
    to absorb further downstream.
    """
    value = values.get(name)
    return str(value).strip() if value is not None else ""


def _redact(text: str, credentials: dict[str, Any]) -> str:
    """Provider error text with every secret in it removed.

    Necessary here for the reason ``error_sanitizer`` was written: an account
    identifier sits in the request URL, and ``httpx``'s default message
    embeds the URL. The carrier's name is exempted, though — it is a public
    identifier that merely shares a dict with an auth token, and redacting it
    rewrites the API host in the message into noise while protecting nothing.
    """
    secrets = {key: value for key, value in credentials.items() if key != _GATEWAY_FIELD}
    return redact_credentials(text, secrets)


def _unreachable(exc: Exception, credentials: dict[str, Any]) -> ValidationResult:
    """The carrier could not be asked, which is not the customer's fault.

    A warning rather than a failure: blocking here would turn a carrier's
    outage — or an egress rule on this installation — into an accusation that
    the customer's credentials are wrong, and would stop a channel that will
    work perfectly once the network settles. The detail rides along as a
    diagnostic value rather than copy, because "we could not reach your
    carrier" with nothing after it is a warning nobody can act on.
    """
    return _finding(
        "connect.sms.check.gatewayUnreachable",
        CHECK_WARN,
        params={"detail": _redact(str(exc), credentials)},
    )


def _rejected(credentials: dict[str, Any], *, detail: str | None = None) -> ValidationResult:
    """The carrier was shown these credentials and said no.

    ``FIX_REENTER`` and never ``FIX_REAUTHORIZE``. The AUTHENTICATE step for
    this connector *is* the form, and a reauthorize fix on a channel with no
    consent screen renders a button the console cannot send anybody to.
    """
    return _finding(
        "connect.sms.check.credentialsRejected",
        CHECK_FAIL,
        params={"detail": _redact(detail, credentials)} if detail else {},
        instructions=None,
    )


def _number_unverified(exc: Exception, credentials: dict[str, Any]) -> ValidationResult:
    """The account answered and then the number list did not.

    A different outcome from ``_rejected``, and the difference is the whole
    point. Both calls carry the same credentials, so once the account call has
    come back 200 those credentials are established fact; a 404 on the number
    list afterwards is a statement about a *number*, a permission-scoped API
    key or a carrier having a moment, and never about the values the customer
    typed. Reporting it as a rejection sent them back to retype an account SID
    that had just been proved correct — and left the real cause unnamed.

    A warning, because what is lost is the *verification* of the sending
    number, not the ability to send from it.
    """
    params = {"detail": _redact(str(exc), credentials)}
    if isinstance(exc, httpx.HTTPStatusError):
        params["status"] = str(exc.response.status_code)
    return _finding("connect.sms.check.numberUnverified", CHECK_WARN, params=params)


def _account_outcomes(details: Mapping[str, Any]) -> tuple[ValidationResult, ...]:
    """What a Twilio account resource says about itself, as checklist lines.

    Both questions are ones only a watching customer can act on: a suspended
    account authenticates perfectly and sends nothing, and a trial account can
    only message numbers it has verified — which is a channel that works for
    whoever tested it and for nobody else.
    """
    outcomes = [_finding("connect.sms.check.credentialsVerified", CHECK_OK)]

    status = _text(details, "status").lower()
    if status and status != "active":
        outcomes.append(
            _finding(
                "connect.sms.check.accountInactive",
                CHECK_FAIL,
                params={"status": status},
                instructions="connect.sms.twilio.fix.activateAccount",
            )
        )
    if _text(details, "type").lower() == "trial":
        outcomes.append(
            _finding(
                "connect.sms.check.accountTrial",
                CHECK_WARN,
                instructions="connect.sms.twilio.fix.leaveTrial",
            )
        )
    return tuple(outcomes)


def _number_outcomes(
    owned: Sequence[Mapping[str, Any]], number: str
) -> tuple[ValidationResult, ...]:
    """Whether the sending number is on this account and can carry SMS.

    The two ways an SMS channel connects cleanly and then fails on its first
    outbound message, and the only moment either is cheap to say.
    """
    match = next((entry for entry in owned if _text(entry, "phone_number") == number), None)
    if match is None:
        return (
            _finding(
                "connect.sms.check.numberNotOnAccount",
                CHECK_FAIL,
                fail_code=ValidationCode.RESOURCE_NOT_ELIGIBLE,
                params={"number": number},
                instructions="connect.sms.twilio.fix.buyNumber",
            ),
        )
    if not (match.get("capabilities") or {}).get("sms"):
        return (
            _finding(
                "connect.sms.check.numberNoSms",
                CHECK_FAIL,
                params={"number": number},
                instructions="connect.sms.twilio.fix.smsCapability",
            ),
        )
    return (_finding("connect.sms.check.numberVerified", CHECK_OK, params={"number": number}),)


async def _twilio_numbers(
    client: httpx.AsyncClient, *, account_sid: str, auth: tuple[str, str], number: str
) -> list[Any]:
    """The account's own entry for one phone number, as Twilio returns it.

    Shared by the probe and by registration because both need the same list
    and neither should learn the other's shape: registration needs the
    number's SID (the REST resource is keyed by it, not by the E.164 address)
    and the probe needs its capabilities. Raises rather than reporting —
    the two callers disagree about what a failure means.
    """
    response = await client.get(
        f"{_TWILIO_API}/Accounts/{account_sid}/IncomingPhoneNumbers.json",
        auth=auth,
        params={"PhoneNumber": number},
    )
    response.raise_for_status()
    found = response.json().get("incoming_phone_numbers") or []
    return list(found)


async def _probe_twilio(credentials: dict[str, Any]) -> tuple[ValidationResult, ...]:
    """What is worth knowing about a Twilio account before connecting it.

    Not a duplicate of ``TwilioGateway.health_check``, which answers "do these
    credentials still work" on a timer. This runs once, with the customer
    watching, and so asks the questions that are only answerable while they
    can still act on the answer: a trial account can only message numbers it
    has verified, a suspended account authenticates perfectly and sends
    nothing, and a sending number that is voice-only or lives under a
    different account produces a channel that saves, reports itself healthy,
    and fails on its first outbound message.

    Two calls, and deliberately two error handlers. Only the first can conclude
    anything about the credentials — see ``_number_unverified``.
    """
    account_sid = _text(credentials, "account_sid")
    auth = (account_sid, _text(credentials, "auth_token"))
    number = _text(credentials, "from_number")

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        try:
            account = await client.get(f"{_TWILIO_API}/Accounts/{account_sid}.json", auth=auth)
            account.raise_for_status()
            details = account.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _REJECTED_STATUS_CODES:
                return (_rejected(credentials),)
            return (_unreachable(exc, credentials),)
        except httpx.InvalidURL as exc:
            # Not an ``httpx.HTTPError``, and raised before any request is
            # made: the identifier is malformed rather than wrong, which is
            # still something only the customer can correct.
            return (_rejected(credentials, detail=str(exc)),)
        except (httpx.HTTPError, ValueError) as exc:
            return (_unreachable(exc, credentials),)

        outcomes = list(_account_outcomes(details))

        try:
            owned = await _twilio_numbers(client, account_sid=account_sid, auth=auth, number=number)
        except Exception as exc:  # noqa: BLE001 - the credentials are already proven
            # Broad on purpose. Whatever happened after a successful account
            # call, the one thing it is not is a rejected credential, and
            # narrowing this would throw away the findings above along with
            # it.
            outcomes.append(_number_unverified(exc, credentials))
            return tuple(outcomes)

        outcomes.extend(_number_outcomes(owned, number))
        return tuple(outcomes)


async def _register_twilio(credentials: dict[str, Any], callback_url: str) -> Repair:
    """Point a Twilio number's ``SmsUrl`` at this installation.

    The call the old module docstring said existed and declined to make, now
    that there is a real channel id in the URL to make it with. Two round
    trips because Twilio keys the number resource by its SID rather than by
    the address the customer typed.

    ``SmsMethod`` is set explicitly rather than left alone: a number carried
    over from an earlier configuration may be on ``GET``, and Twilio then
    delivers the message in the query string, where ``TwilioGateway`` — which
    parses a form-encoded body — finds an empty message it cannot even
    attribute to a sender.

    Returns rather than raises, and returns no credentials and no webhook
    secret: nothing about this call changes what is stored. Twilio signs with
    the auth token already in ``credentials``, so a secret returned here would
    populate a column nothing verifies against.
    """
    account_sid = _text(credentials, "account_sid")
    auth = (account_sid, _text(credentials, "auth_token"))
    number = _text(credentials, "from_number")

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            owned = await _twilio_numbers(client, account_sid=account_sid, auth=auth, number=number)
            number_sid = next(
                (
                    str(entry["sid"])
                    for entry in owned
                    if _text(entry, "phone_number") == number and entry.get("sid")
                ),
                None,
            )
            if number_sid is None:
                # Distinct from a failed call: the account is reachable and
                # the credentials work, the number simply is not on it. The
                # checklist says the same thing before connecting, so this is
                # the case where somebody moved the number afterwards.
                return Repair(repaired=False, reason=_ERROR_NUMBER_NOT_ON_ACCOUNT)

            updated = await client.post(
                f"{_TWILIO_API}/Accounts/{account_sid}/IncomingPhoneNumbers/{number_sid}.json",
                auth=auth,
                # Verbatim. See the module docstring: Twilio signs the URL it
                # was given, and the ingress rebuilds it from the request path.
                data={"SmsUrl": callback_url, "SmsMethod": "POST"},
            )
            updated.raise_for_status()
    except Exception:  # noqa: BLE001 - a failed registration is a reason, not a crash
        # This runs after the channel row exists. Raising would abort a
        # connect that has already succeeded in every way that matters —
        # outbound works — over a callback the customer can also set by hand.
        return Repair(repaired=False, reason=_ERROR_WEBHOOK_REGISTRATION)

    return Repair(repaired=True)


@dataclass(frozen=True, slots=True)
class _Gateway:
    """One carrier, described from the wizard's side rather than the wire's.

    ``SmsGateway`` knows how to *use* a carrier's credentials; this knows how
    to *obtain* them — which fields to ask for, which of them names the
    sending number, and how to tell the customer something useful before they
    commit. Both halves are per-carrier and neither can be derived from the
    other, so adding Vonage is a subclass there and an entry here. That is the
    cost of the union form being honest, and it is paid in one file each.
    """

    name: str
    label_key: str
    fields: tuple[CredentialSpec, ...]
    #: The field holding the E.164 address the channel sends from — its
    #: identity to the outside world, and what a customer recognises it by.
    number_field: str
    #: The field naming the carrier account the number hangs off, where the
    #: carrier has such a concept.
    account_field: str | None = None
    #: What to tell the customer at VERIFY. ``None`` for a carrier we can
    #: collect credentials for but have nothing to say about — silence is
    #: better than a checklist that only ever reports success.
    probe: Callable[[dict[str, Any]], Awaitable[tuple[ValidationResult, ...]]] | None = None
    #: How to point this carrier at a callback URL, for a carrier that has an
    #: API for it. ``None`` is what a manual-paste warning on the checklist
    #: means, and what keeps ``AUTOMATIC_WEBHOOK_REGISTRATION`` honest on a
    #: build that ships only such carriers.
    register: Callable[[dict[str, Any], str], Awaitable[Repair]] | None = None


_TWILIO = _Gateway(
    name="twilio",
    label_key="connect.sms.gatewayOption.twilio",
    number_field="from_number",
    account_field="account_sid",
    fields=(
        CredentialSpec(
            name="account_sid",
            kind="text",
            label_key="connect.sms.twilio.accountSidLabel",
            help_key="connect.sms.twilio.accountSidHelp",
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        ),
        CredentialSpec(
            name="auth_token",
            kind="secret",
            label_key="connect.sms.twilio.authTokenLabel",
            # Worth its own copy: this one value both authorises outbound
            # sends and verifies every inbound delivery's signature, so
            # rotating it in the carrier's console silently breaks both
            # directions at once.
            help_key="connect.sms.twilio.authTokenHelp",
        ),
        CredentialSpec(
            name="from_number",
            kind="text",
            label_key="connect.sms.twilio.fromNumberLabel",
            help_key="connect.sms.twilio.fromNumberHelp",
            placeholder="+15551234567",
        ),
    ),
    probe=_probe_twilio,
    register=_register_twilio,
)

_GATEWAYS: dict[str, _Gateway] = {_TWILIO.name: _TWILIO}


def _selectable_gateways() -> tuple[_Gateway, ...]:
    """Carriers this build can both configure and send with.

    The intersection matters in both directions. One this file describes but
    the build never registered would offer a customer a carrier whose messages
    have nowhere to go; one registered but undescribed cannot be given a
    credentials form, and offering it would strand the customer at the last
    step of a flow that promised two minutes. Ordered by name so the select
    does not reshuffle itself when an import moves — the reason the connector
    registry sorts too.
    """
    return tuple(
        _GATEWAYS[name] for name in sorted(SmsGatewayRegistry.known_gateways()) if name in _GATEWAYS
    )



def _finding(
    check: str,
    level: str,
    *,
    params: dict[str, str] | None = None,
    fail_code: ValidationCode = ValidationCode.INVALID_TOKEN,
    repair: str | None = None,
    instructions: str | None = None,
) -> ValidationResult:
    """One finding, from this module's own check vocabulary.

    SMS reports more distinct conditions than any other connector here —
    account state, trial restrictions, a number's existence, its SMS
    capability, whether the carrier can register a callback — and each was
    written as a check key plus a severity. Mapping them here rather than at
    twenty call sites keeps the severity-to-code translation in one readable
    place, and keeps the specific check key, which is what the console's copy
    is actually written against.

    ``fail_code`` is explicit because "this failed" is not one thing: a
    rejected credential and a number that cannot send SMS need different
    words and different next actions.
    """
    code = (
        ValidationCode.OK
        if level == CHECK_OK
        else ValidationCode.ADVISORY
        if level == CHECK_WARN
        else fail_code
    )
    return ValidationResult(
        code,
        channel_type="sms",
        params={**(params or {}), "check": check},
        repair_action=repair,
        instructions_key=instructions,
    )

def _requires(gateway: _Gateway, name: str) -> bool:
    return any(field.name == name and field.required for field in gateway.fields)


def _union_credential_specs(gateways: tuple[_Gateway, ...]) -> tuple[CredentialSpec, ...]:
    """Every carrier's fields, once each, required only where all agree.

    Field names are the carrier's own credential keys, so two carriers sharing
    a name share a meaning (``from_number`` is a sending address whoever
    delivers it) and the first description of it is the right one. Requiredness
    cannot be shared that way: enforcing one carrier's needs on a customer who
    chose another is a form that cannot be submitted, so the union asks for
    only what nobody can do without and the chosen carrier's real requirements
    are enforced where the choice is known.

    Every other attribute is carried across untouched, and the rebuild is a
    ``replace`` for exactly that reason: an earlier version listed the fields
    it copied and silently dropped ``options`` and ``copyable``, which turned
    the second carrier's ``select`` into an empty dropdown and threw away the
    one piece of copy that keeps a customer from opening a vendor's
    documentation. A field's description belongs to the carrier that wrote it;
    requiredness is the single thing the union is entitled to overrule.
    """
    union: dict[str, CredentialSpec] = {}
    for gateway in gateways:
        for field in gateway.fields:
            union.setdefault(field.name, field)
    return tuple(
        CredentialSpec(
            name=field.name,
            kind=field.kind,
            label_key=field.label_key,
            required=all(_requires(gateway, field.name) for gateway in gateways),
            help_key=field.help_key,
            placeholder=field.placeholder,
            options=field.options,
            copyable=field.copyable,
        )
        for field in union.values()
    )


def _chosen_gateway(values: Mapping[str, Any]) -> _Gateway | None:
    """The carrier named in a submitted form, or ``None`` if it is not one.

    Checked against the transport registry as well as this file's table,
    because a value that reaches storage without being registered becomes an
    ``InvalidSmsGatewayError`` at the first inbound webhook — a failure the
    customer meets long after the wizard told them everything was fine.
    """
    name = _text(values, _GATEWAY_FIELD)
    if name not in SmsGatewayRegistry.known_gateways():
        return None
    return _GATEWAYS.get(name)


def _webhook_setup_outcome(gateway: _Gateway) -> ValidationResult:
    """What is left for the customer to do about inbound, if anything.

    Per carrier now that one of them can be configured from here: a Twilio
    number is pointed at us by ``register_webhook`` as soon as the channel has
    an id, so the honest line is that nothing is required of them. A carrier
    with no registration hook keeps the warning it always had.
    """
    if gateway.register is not None:
        return _finding("connect.sms.check.webhookAutomatic", CHECK_OK)
    return _finding(
        "connect.sms.check.webhookManualSetup",
        CHECK_WARN,
        instructions="connect.sms.fix.setInboundWebhook",
    )


@ConnectorRegistry.register("sms")
class SmsConnector(Connector):
    """Connecting an SMS number, whichever carrier delivers it."""

    channel_type = "sms"
    app_key = None
    #: The only manifest here that is *computed*, and the reason is the
    #: second plugin level: which fields to ask for depends on which carriers
    #: this build shipped. It is still stable for the life of the process —
    #: gateways register at import time — so the console can cache it as
    #: safely as any other, but a connector whose form is a union of its
    #: carriers' forms cannot state that union as a literal.
    @property
    def manifest(self) -> ConnectorManifest:
        gateways = _selectable_gateways()
        credentials: tuple[CredentialSpec, ...] = ()
        if gateways:
            credentials = (
                CredentialSpec(
                    name=_GATEWAY_FIELD,
                    kind="select",
                    label_key="connect.sms.gatewayLabel",
                    help_key="connect.sms.gatewayHelp",
                    options=tuple(
                        (gateway.name, gateway.label_key) for gateway in gateways
                    ),
                ),
                *_union_credential_specs(gateways),
            )
        return ConnectorManifest(
            channel_type="sms",
            name_key="connect.sms.name",
            description_key="connect.sms.description",
            category=ConnectorCategory.SMS,
            icon="sms",
            capabilities=frozenset(
                {
                    Capability.MANUAL_CONFIGURATION,
                    Capability.WEBHOOKS,
                    Capability.AUTOMATIC_WEBHOOK_REGISTRATION,
                    Capability.HEALTH_CHECKS,
                }
            ),
            auth_methods=(AuthMethod.CREDENTIALS,),
            required_credentials=credentials,
            verification_steps=(
                VerificationSpec(
                    key="connect.sms.check.account",
                    title_key="connect.sms.check.account.title",
                    codes=(
                        ValidationCode.OK,
                        ValidationCode.MISSING_CREDENTIAL,
                        ValidationCode.INVALID_TOKEN,
                        ValidationCode.PROVIDER_UNREACHABLE,
                    ),
                ),
                VerificationSpec(
                    key="connect.sms.check.number",
                    title_key="connect.sms.check.number.title",
                    codes=(
                        ValidationCode.OK,
                        ValidationCode.RESOURCE_NOT_ELIGIBLE,
                        ValidationCode.ADVISORY,
                    ),
                ),
            ),
            repair_actions=(
                RepairAction(
                    id=_REREGISTER_WEBHOOK,
                    title_key="connect.sms.repair.reregisterWebhook.title",
                    description_key="connect.sms.repair.reregisterWebhook.description",
                ),
            ),
            # No images: SmsProvider refuses outbound attachments, and a
            # customer should learn that here rather than from a failed send.
            supported_features=("text",),
        )

    def resolve(self, context: DeploymentContext) -> ConnectorProfile:
        """The default answer, adjusted for what this build actually ships.

        The only connector here whose availability turns on what else was
        compiled in rather than on what the installation was given — a
        consequence of the second plugin level, and the one case the default
        resolution cannot express, since it reasons about provider apps.

        Two build-dependent answers rather than one. No configurable carrier
        at all is a dead end and every capability says so. Carriers but no
        registration hook among them is a channel that connects perfectly and
        simply cannot promise automatic inbound setup, which is a single
        capability turned off with its own reason — not a channel withdrawn.

        A build that ships one carrier which registers and one which does not
        reports the capability *available*, because it is: it is offered
        wherever it applies, and the checklist tells the customer which of the
        two they chose. Anything else would deny the promise to Twilio
        customers to avoid over-promising to Vonage ones, and the capability
        set is resolved per deployment — the carrier is not chosen until the
        form is submitted, two steps later.
        """
        gateways = _selectable_gateways()
        if not gateways:
            return ConnectorProfile(
                channel_type=self.channel_type,
                declares=self.declares,
                states=tuple(
                    CapabilityState(capability, available=False, reason=_NO_GATEWAY)
                    for capability in sorted(self.declares, key=lambda c: c.value)
                ),
            )

        resolved = super().resolve(context)
        if any(gateway.register is not None for gateway in gateways):
            return resolved
        return ConnectorProfile(
            channel_type=resolved.channel_type,
            declares=resolved.declares,
            states=tuple(
                CapabilityState(state.capability, available=False, reason=_NO_WEBHOOK_REGISTRATION)
                if state.capability is Capability.AUTOMATIC_WEBHOOK_REGISTRATION
                else state
                for state in resolved.states
            ),
        )

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        """Everything worth saying before an SMS channel is written down.

        ``attempt.credentials`` is the submitted form. This connector has no
        consent step, so ``grant`` is empty and the property resolves to
        ``inputs`` — which is why nothing here has to know which of the two it
        was handed.

        Nothing raises: an exception would collapse a list of findings into
        whichever one happened to be evaluated first, so even a carrier that
        fails in a way no probe anticipated becomes an outcome the customer
        can read.
        """
        credentials = dict(attempt.credentials)
        gateway = _chosen_gateway(credentials)
        if gateway is None:
            return (
                _finding(
                    "connect.sms.check.gatewayUnknown",
                    CHECK_FAIL,
                    fail_code=ValidationCode.MISSING_CREDENTIAL,
                    params={"gateway": _text(credentials, _GATEWAY_FIELD)},
                    instructions=None,
                ),
            )

        # The union form could not demand these; this is where the carrier's
        # own requirements are finally enforced, one outcome per field so the
        # customer fixes them all in one pass instead of one per attempt.
        missing = tuple(
            field.name
            for field in gateway.fields
            if field.required and not _text(credentials, field.name)
        )
        if missing:
            return tuple(
                _finding(
                    "connect.sms.check.credentialMissing",
                    CHECK_FAIL,
                    fail_code=ValidationCode.MISSING_CREDENTIAL,
                    params={"field": name},
                    instructions=None,
                )
                for name in missing
            )

        outcomes: list[ValidationResult] = []
        if gateway.probe is not None:
            try:
                outcomes.extend(await gateway.probe(credentials))
            except Exception as exc:  # noqa: BLE001 - see docstring
                outcomes.append(_unreachable(exc, credentials))

        outcomes.append(_webhook_setup_outcome(gateway))
        return tuple(outcomes)

    async def connect(self, *, company_id: UUID, attempt: Attempt) -> tuple[Connection, ...]:
        """One channel: one carrier account, one sending number.

        Nothing is registered with the carrier and no secret is generated. The
        callback URL still does not exist at this point — that is what
        ``register_webhook`` is for — and the token that verifies inbound
        signatures is one of the values being stored. What is written down is
        exactly the dict ``SmsProvider`` will later hand its gateway: the
        carrier's name plus that carrier's own credential keys, and nothing
        this layer invented.
        """
        values = dict(attempt.credentials)
        gateway = _chosen_gateway(values)
        if gateway is None:
            raise InvalidSmsGatewayError(_text(values, _GATEWAY_FIELD))

        stored: dict[str, Any] = {_GATEWAY_FIELD: gateway.name}
        missing: list[str] = []
        for field in gateway.fields:
            value = values.get(field.name)
            if isinstance(value, str):
                value = value.strip()
            if value is None or value == "":
                if field.required:
                    missing.append(field.name)
                continue
            stored[field.name] = value
        if missing:
            # Reachable only when the checklist was bypassed, and worth
            # refusing anyway: a credentials dict missing a key the gateway
            # dereferences produces a channel that saves and never sends.
            #
            # A key rather than ``f"missing: {', '.join(missing)}"``. That
            # detail is rendered to the customer by the API's error handler,
            # where an English sentence composed here can never be translated
            # — and the customer has already been told which fields, one
            # outcome each, by ``check``.
            raise InvalidChannelCredentialsError(self.channel_type, _ERROR_CREDENTIAL_MISSING)

        number = str(stored.get(gateway.number_field, ""))
        parent = stored.get(gateway.account_field) if gateway.account_field else None
        return (
            Connection(
                channel_type=self.channel_type,
                # What the customer called it, and otherwise the number: not a
                # translated label, because the number is the name they know
                # this channel by and the one an agent sees against a
                # conversation.
                display_name=attempt.display_name.strip() or number or gateway.name,
                credentials=stored,
                external_id=number or None,
                external_parent_id=str(parent) if parent else None,
                # See the module docstring: the carrier's own signing secret
                # is already in ``credentials``.
                webhook_secret=None,
            ),
        )

    async def register_webhook(
        self, *, callback_url: str, credentials: dict[str, Any], context: DeploymentContext
    ) -> Repair:
        """Point the chosen carrier at this channel's ingress URL.

        Everything this connector could not do inside ``connect``, done at the
        one moment it is possible: the channel row exists, so ``callback_url``
        names a route that will actually answer, and there is no invented id
        anywhere in it.

        ``context`` is unused. The URL arrives complete — deriving one here
        from ``public_base_url`` would mean this connector guessing the API
        prefix and the channel id it was just handed.
        """
        gateway = _chosen_gateway(credentials)
        if gateway is None:
            # Stored credentials naming a carrier this build cannot load. The
            # channel exists and cannot send either, but that is not this
            # hook's failure to report.
            return Repair(repaired=False, reason=_ERROR_GATEWAY_UNKNOWN)
        if gateway.register is None:
            return Repair(repaired=False, reason=_NOT_SUPPORTED)
        return await gateway.register(credentials, callback_url)

    async def repair(
        self,
        *,
        action: str,
        credentials: dict[str, Any],
        webhook_secret: str | None = None,
        callback_url: str | None = None,
        context: DeploymentContext,
    ) -> Repair:
        """Put the callback back, when a customer's carrier has lost it.

        Worth a button because a number's ``SmsUrl`` is a field in the
        carrier's console that anybody with access can change, and every
        symptom of it having been changed is silence. The repair is the same
        call ``register_webhook`` makes, against the same URL, which is what
        keeps pressing it idempotent rather than a way to accumulate
        registrations.

        ``webhook_secret`` is deliberately ignored and never returned. Twilio
        signs with the auth token in ``credentials``; there is no per-channel
        secret to rotate here, and returning one would write a column that
        nothing on the inbound path reads.
        """
        if action != _REREGISTER_WEBHOOK:
            return Repair(repaired=False, reason=_NOT_SUPPORTED)
        if not callback_url:
            # Nothing to register against. Said as a reason rather than an
            # invented URL: a callback the carrier accepts and nothing answers
            # is worse than a repair that admits it could not run.
            return Repair(repaired=False, reason=_ERROR_NO_CALLBACK_URL)
        return await self.register_webhook(
            callback_url=callback_url, credentials=credentials, context=context
        )


__all__ = ["SmsConnector"]
