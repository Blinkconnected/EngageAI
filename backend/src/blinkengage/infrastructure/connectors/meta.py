"""Meta — WhatsApp, Messenger and Instagram, as one connector family.

Three channel types, one provider app, one consent. That is not a convenience:
it is the reason a customer connecting "Instagram + Messenger" is asked to
approve once rather than twice, and the reason the Full Meta Suite template
exists at all. The three subclasses at the bottom differ only in what they
discover and what they call the resource they end up with.

**Everything Meta-specific in the product lives in this file.** The wizard
that drives it does not know Meta exists — it asks this connector what it can
do and renders the answer. That is the whole architecture, and the way to
check it still holds is to grep for "meta" outside this module and the
registry that imports it.

Two structural facts about Meta's app model shape the design, and both are
unusual enough to state plainly:

**The webhook is configured on the app, not on the channel.** Under a shared
app every tenant's WhatsApp, Page and Instagram events arrive at one
installation-wide callback and are fanned out by the ids in the payload. The
per-channel callback URL that every other connector uses does not exist here,
which is why ``SHARED_WEBHOOK`` is declared and why ``Connection`` carries
``external_id`` — that id is how an inbound event finds its way back to a
channel. It also means the App Secret is a property of the *installation*
rather than of a channel row, so ``webhook_secret`` comes back ``None``:
storing a copy per channel would be one plaintext copy of the highest-value
secret we hold, per channel, forever. It is also why these connectors do not
implement ``register_webhook`` — see the comment above ``_subscribe``.

**OAuth needs an app we do not necessarily have.** No installation is born
with Meta credentials, and obtaining them is weeks of app review rather than
an afternoon of code. So the capabilities resolve per deployment — the base
``Connector.resolve`` already withholds OAuth when no app is configured — and
the manual path is kept permanently rather than as a transitional courtesy.
It is the only path for a self-hosted installation with no app, the fallback
when consent fails, and the one that works while review is pending.

Two declarations elsewhere in this file follow directly from that second fact
and are worth finding here rather than in a comment halfway down:

**These three are ``PREVIEW``, not ``BETA``.** The consent half of the flow
cannot execute. ``authorize_url`` builds a dialog URL containing a literal
``{app_id}`` because no app id is plumbed to it, and ``exchange`` is not
overridden at all, so the base's ``NotImplementedError`` is what a callback
would reach. Discovery only ever runs on a grant, so it is unreachable too.
The manual path is complete and tested, which is why this is a connector with
a broken half rather than one that does not work — but "feature-complete and
being proven" is a claim about the whole connector, and half of this one has
never run. See ``Maturity`` on the two axes a badge is resolved from.

**The feature matrix is read off the transport, not off Meta's product
pages.** Every row below was checked against ``providers/whatsapp.py`` and
``providers/_meta_messaging.py``, and a capability those files stub out is
absent here even where the provider's API has it. WhatsApp's
``typing_indicator`` is a documented no-op and Messenger's ``mark_as_read``
is another, so neither channel claims the corresponding feature; Messenger
and Instagram parse an inbound ``reply_to`` but never send one, so their
threading is inbound-only. A matrix that described the provider rather than
our client would be wrong in exactly the cases a customer notices.

**Certification runs the transport's own requests, and skips whatever it
cannot make Graph answer.** ``run_scenario`` sends through the same Send API
shapes ``providers/whatsapp.py`` and ``providers/_meta_messaging.py`` use, so
a pass means the request the product will make at 3am was accepted today; the
authentication and webhook scenarios call ``diagnose`` itself rather than a
second copy of it, so the certification report and the diagnostics panel
cannot disagree about the same token. Four scenarios these connectors claim
have no executable form at all — every one of them needs a message a customer
sent — and they report ``SKIPPED`` with the reason rather than a pass earned
against a fixture. See ``_unexecutable``, which is the part of this file worth
reading first.
"""

from __future__ import annotations

import asyncio
import json
import math
from base64 import b64decode
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
    DeploymentContext,
    Field,
    Repair,
    Resource,
)
from blinkengage.domain.connector_certification import (
    EMITS_TO_A_CUSTOMER,
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
    ResourceSpec,
    ValidationCode,
    ValidationResult,
    VerificationSpec,
)
from blinkengage.domain.connectors import (
    FIX_REAUTHORIZE,
    FIX_REENTER,
    Capability,
    Fix,
)
from blinkengage.infrastructure.channels.error_sanitizer import redact_credentials
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: Matches the transport providers' own defaults so a channel connected here
#: and a message sent later talk to the same Graph.
GRAPH_BASE = "https://graph.facebook.com"
GRAPH_VERSION = "v21.0"

#: The one app key the three connectors share. One entry in
#: ``DeploymentContext.configured_apps`` enables all of them, which is exactly
#: the relationship the templates rely on.
META_APP = "meta"

#: The one repair these connectors offer, named once so the string in
#: ``repair`` and the string a ``Fix`` would carry cannot drift apart.
REREGISTER_WEBHOOK = "reregister_webhook"

#: How long a Graph call may take before the wizard gives up on it. Short:
#: this runs while a customer watches a spinner, and a connector that hangs
#: for thirty seconds has already failed the two-minute promise.
TIMEOUT = 10.0

#: Shorter still for diagnostics, because two of them run inside one budget.
#: ``ChannelDiagnosticsService`` gives a connector twelve seconds for its
#: whole report; two ten-second calls would spend it and the panel would show
#: nothing at exactly the moment somebody needed it. They are also issued
#: concurrently, so this is the wall-clock cost of the pair rather than of
#: each.
DIAGNOSTIC_TIMEOUT = 5.0

#: How close to expiry a token gets before the panel says so. A week is long
#: enough that somebody sees it during a working week and short enough that
#: it is not permanently amber on a sixty-day Page token.
EXPIRY_WARNING_DAYS = 7

#: How long one certification call may take. The runner allows a scenario
#: twenty seconds and the media scenario spends two calls inside that budget
#: (upload, then send), so this is deliberately under half of it — and larger
#: than ``DIAGNOSTIC_TIMEOUT``, because a media upload is a body on the wire
#: rather than a token being read back.
CERTIFICATION_TIMEOUT = 8.0

#: What a certification send actually puts in front of whoever owns the
#: target, and the one customer-visible string in this module that is not a
#: translation key. It cannot be one: this is *message content* handed to
#: Meta, so a key would arrive on somebody's phone reading
#: ``certification.send.body``. Short and self-identifying, because the only
#: question its reader has is what it is and who sent it.
CERTIFICATION_MESSAGE = "Blink Engage: channel certification test."

#: A 1×1 PNG — the smallest thing that is genuinely an image to Meta's
#: decoder. The media scenario has to upload something real, and the
#: alternative is a picture file we ship, pay for on every run, and deliver to
#: somebody's test handset for no benefit over seventy bytes.
CERTIFICATION_IMAGE = b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    b"DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CERTIFICATION_IMAGE_TYPE = "image/png"
CERTIFICATION_IMAGE_NAME = "certification.png"

#: When Meta stops serving a Graph version, for versions somebody has actually
#: read off Meta's published table
#: (https://developers.facebook.com/docs/graph-api/changelog/versions, read
#: 2026-07-30). Meta is one of the few providers that publishes this at all,
#: which is the entire reason ``Connector.supported_until`` exists — Telegram
#: has no such concept and answers ``None``.
#:
#: Keyed by version rather than written as one constant, and that is the whole
#: design: bumping ``GRAPH_VERSION`` without re-reading Meta's table yields
#: ``None`` — "nobody has checked" — instead of quietly attaching v21.0's
#: retirement date to a version with its own. An administrator plans a
#: migration around this date, so a stale one plans the wrong migration, which
#: is worse than planning none. For the same reason there is one row and not a
#: transcription of the whole table: a date for a version no code here speaks
#: is a date nobody would re-verify on the day it started being used.
GRAPH_VERSION_SUNSET: dict[str, date] = {
    # Released 2024-10-02, retired 2027-01-21 — two years after its successor
    # shipped, which is the rule every row of Meta's table follows.
    "v21.0": date(2027, 1, 21),
}

#: What these connectors are, what they speak, and what they need. ``api`` is
#: read from ``GRAPH_VERSION`` rather than restated, so the version a customer
#: is told about and the version the code calls cannot drift — which is the
#: entire reason a customer would look at this field.
META_VERSIONS = VersionInfo(connector="1.0.0", api=GRAPH_VERSION, minimum_platform="1.0.0")

#: The three rows every Meta channel earns, verified against the transport.
#: All three providers send text and attachments and parse both back out of
#: the webhook, so these are the only unqualified entries in the family.
CORE_FEATURES: tuple[FeatureSupport, ...] = (
    FeatureSupport(ChannelFeature.SEND_MESSAGES, Direction.OUTBOUND),
    FeatureSupport(ChannelFeature.RECEIVE_MESSAGES, Direction.INBOUND),
)


class MetaError(RuntimeError):
    """A Graph call failed in a way the customer needs to hear about."""


async def _graph(
    path: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    method: str = "GET",
    base: str = GRAPH_BASE,
    version: str = GRAPH_VERSION,
) -> dict[str, Any]:
    """One Graph call, with the token kept out of anything that escapes.

    Meta returns errors as ``{"error": {...}}`` with HTTP 200 as often as not,
    so the body is checked rather than only the status. The message is
    surfaced to the caller but redacted first: Graph echoes request context
    into errors, and the access token is in the request.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(
            method,
            f"{base}/{version}/{path.lstrip('/')}",
            params={**(params or {}), "access_token": token},
        )
    try:
        body = response.json()
    except ValueError as exc:  # pragma: no cover - Graph always sends JSON
        raise MetaError("meta.error.unreadableResponse") from exc
    if isinstance(body, dict) and "error" in body:
        detail = str(body["error"].get("message", "")) or "unknown"
        raise MetaError(redact_credentials(detail, {"access_token": token}))
    if response.status_code >= 400:
        raise MetaError(f"meta.error.http.{response.status_code}")
    return body if isinstance(body, dict) else {"data": body}


@dataclass(frozen=True, slots=True)
class _Probe:
    """One Graph call, classified rather than raised.

    ``reached`` is the distinction the whole report hangs on. Graph answering
    "this token is invalid" and Graph never answering at all collapse into one
    exception for ``_graph``'s callers, and that is right for them — the
    wizard tells a customer to try again either way. A diagnostics panel must
    keep them apart: reporting an unreachable provider as a credential failure
    sends a support engineer rotating a token that was never the problem,
    during an outage, while a customer waits. Certification needs the same
    distinction for the same reason and one step further on — an unreachable
    Meta is a scenario nobody measured, not a scenario that failed.
    """

    #: The parsed body, present only when Graph answered cleanly.
    body: dict[str, Any] | None = None
    #: True when Graph responded at all, however badly.
    reached: bool = False
    #: Already redacted, and never shown without a ``detail_key`` in front.
    detail: str = ""
    #: Graph's own error code, when it sent an error envelope. Kept because
    #: it is the only thing separating "your credential is wrong" from "ask
    #: again in five minutes" — both arrive with the same shape.
    error_code: int | None = None
    #: The subcode, where Graph sends one. Meta's send failures are routinely
    #: one code with several subcodes meaning entirely different things — code
    #: 10 is both "your app lacks permission" and "this thread is outside the
    #: 24-hour window", and only the subcode says which.
    error_subcode: int | None = None
    #: Kept as evidence rather than for a decision: the body is what these
    #: calls are judged on, but a support engineer reading a failed scenario
    #: wants the number Meta actually returned.
    status_code: int | None = None


async def _attempt(
    method: str,
    path: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: float = DIAGNOSTIC_TIMEOUT,
) -> _Probe:
    """A call that cannot fail, for a caller that must not.

    Deliberately not ``_graph``: this needs the things ``_graph`` discards on
    its way to raising — whether the response came from Meta at all, whether
    the body was an error envelope or a payload, and the codes inside it — and
    bending ``_graph`` to return them would change the behaviour ``validate``,
    ``connect`` and ``repair`` are written against. The URL and the version
    still come from the same constants, so the two paths cannot end up talking
    to different Graphs.

    Writes go through here as well as reads, because a certification send has
    exactly the same problem as a diagnostic probe: it has to tell "Meta said
    no" from "Meta said nothing", and an exception says neither.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{GRAPH_BASE}/{GRAPH_VERSION}/{path.lstrip('/')}",
                params={**(params or {}), "access_token": token},
                json=payload,
                data=form,
                files=files,
            )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # Never got there. The token is in the request, and httpx puts the
        # request in the exception, so this is redacted like everything else
        # that escapes this module.
        return _Probe(detail=redact_credentials(str(exc), {"access_token": token}))
    try:
        body = response.json()
    except ValueError:  # pragma: no cover - Graph always sends JSON
        return _Probe(reached=True, detail="unreadable", status_code=response.status_code)
    if not isinstance(body, dict):
        return _Probe(reached=True, detail="unreadable", status_code=response.status_code)
    error = body.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")) or "unknown"
        raw_code = error.get("code")
        raw_subcode = error.get("error_subcode")
        return _Probe(
            reached=True,
            detail=redact_credentials(message, {"access_token": token}),
            error_code=raw_code if isinstance(raw_code, int) else None,
            error_subcode=raw_subcode if isinstance(raw_subcode, int) else None,
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        return _Probe(
            reached=True, detail=str(response.status_code), status_code=response.status_code
        )
    return _Probe(body=body, reached=True, status_code=response.status_code)


async def _probe(path: str, *, token: str, params: dict[str, str] | None = None) -> _Probe:
    """The read half of ``_attempt``, named for what ``diagnose`` does."""
    return await _attempt("GET", path, token=token, params=params)


#: Graph error codes that mean "ask again later", not "your credential is
#: wrong". 4/17/32/613 are rate limits of various kinds; 1 and 2 are
#: transient platform errors. They arrive in the same envelope as a genuine
#: rejection, and telling them apart is the difference between an engineer
#: waiting five minutes and an engineer rotating a working token.
_TRANSIENT_GRAPH_CODES = frozenset({1, 2, 4, 17, 32, 613})


def _is_transient(probe: object) -> bool:
    code = getattr(probe, "error_code", None)
    return isinstance(code, int) and code in _TRANSIENT_GRAPH_CODES


#: Graph errors that mean "not this recipient, not right now" rather than
#: "this channel is broken". A certification target is a number or a PSID
#: somebody typed into a box, and the ordinary way it goes stale is that the
#: person behind it last wrote in more than twenty-four hours ago — at which
#: point Meta refuses the send by policy, on a channel that works perfectly.
#: Scoring that as a failure would grade a healthy channel ``NOT_READY``
#: because a test handset went quiet, and the administrator's next action
#: would be to debug a connector that is fine.
#:
#: - 131026 the recipient cannot receive WhatsApp messages at all
#: - 131030 the recipient is not on the app's allowed list (development mode)
#: - 131047 more than 24 hours since they last wrote; needs a template
#: - 551 Messenger's "this person isn't available right now"
#:
#: Deliberately short. Anything not listed is reported as a failure with
#: Meta's code attached, because guessing at what an unrecognised code meant
#: is how a genuinely broken channel gets certified.
_RECIPIENT_DECLINED_CODES = frozenset({131026, 131030, 131047, 551})

#: Send API subcode for "outside the allowed messaging window". Meta sends it
#: under code 10, which on its own also means "your app lacks this
#: permission" — a real finding. Only the subcode separates them.
_RECIPIENT_DECLINED_SUBCODES = frozenset({2018278})


def _target_declined(probe: _Probe) -> bool:
    return (
        probe.error_code in _RECIPIENT_DECLINED_CODES
        or probe.error_subcode in _RECIPIENT_DECLINED_SUBCODES
    )


#: What a diagnostic status means to a scenario. ``UNKNOWN`` becomes
#: ``SKIPPED`` and not ``FAIL``, which is the whole point of both vocabularies
#: meeting here: ``diagnose`` says ``UNKNOWN`` exactly when it could not
#: measure — Graph unreachable, Graph throttling us — and certification calls
#: an unmeasured scenario an unanswered question rather than a broken channel.
#: It costs coverage, which is the honest price, and not score, which would be
#: a lie about the connector.
_OUTCOME_OF_STATUS: dict[DiagnosticStatus, Outcome] = {
    DiagnosticStatus.OK: Outcome.PASS,
    DiagnosticStatus.WARN: Outcome.WARNING,
    DiagnosticStatus.FAIL: Outcome.FAIL,
    DiagnosticStatus.UNKNOWN: Outcome.SKIPPED,
}

#: The scenarios these connectors claim and cannot execute, and the reason
#: each is unexecutable. See ``MetaConnector._unexecutable``.
_UNEXECUTABLE: dict[ScenarioKind, str] = {
    ScenarioKind.RECEIVE_MESSAGE: "certification.skipped.needsInboundMessage",
    ScenarioKind.MEDIA_DOWNLOAD: "certification.skipped.needsInboundMedia",
    ScenarioKind.READ_RECEIPT: "certification.skipped.needsInboundMessageId",
    ScenarioKind.DISCONNECT: "certification.skipped.noProviderDisconnect",
}


def _skipped(kind: ScenarioKind, detail_key: str, **evidence: str) -> ScenarioResult:
    """A scenario that did not run, and why."""
    return ScenarioResult(
        kind=kind, outcome=Outcome.SKIPPED, detail_key=detail_key, diagnostics=dict(evidence)
    )


def _evidence(probe: _Probe) -> dict[str, str]:
    """What the call is worth keeping regardless of how it came out.

    Diagnostics, not copy: a status code and Meta's own error code are what
    somebody pastes into a support ticket, and they are useless translated.
    """
    found: dict[str, str] = {}
    if probe.status_code is not None:
        found["status_code"] = str(probe.status_code)
    if probe.error_code is not None:
        found["error_code"] = str(probe.error_code)
    if probe.error_subcode is not None:
        found["error_subcode"] = str(probe.error_subcode)
    if probe.detail:
        found["detail"] = probe.detail
    return found


def _refusal(
    kind: ScenarioKind,
    probe: _Probe,
    *,
    failure_key: str,
    extra: dict[str, str] | None = None,
) -> ScenarioResult | None:
    """Why a call does not count, or ``None`` when it did what was asked.

    Three of the four answers are ``SKIPPED``, and each is a case where
    ``FAIL`` would blame the connector for something that is not the
    connector: Meta being unreachable, Meta throttling the app, and Meta
    declining this particular recipient. Only a rejection that is actually
    about this channel — a bad token, a missing permission, a malformed send —
    reaches the last line.
    """
    if probe.body is not None:
        return None
    diagnostics = {**_evidence(probe), **(extra or {})}
    if not probe.reached:
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.SKIPPED,
            detail_key="certification.skipped.providerUnreachable",
            diagnostics=diagnostics,
        )
    if _is_transient(probe):
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.SKIPPED,
            detail_key="certification.skipped.providerThrottled",
            diagnostics=diagnostics,
        )
    if _target_declined(probe):
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.SKIPPED,
            detail_key="certification.skipped.targetNotReachable",
            diagnostics=diagnostics,
        )
    return ScenarioResult(
        kind=kind, outcome=Outcome.FAIL, detail_key=failure_key, diagnostics=diagnostics
    )


class MetaConnector(Connector):
    """Shared behaviour for the three Meta channels.

    Not registered itself — it has no channel type of its own. Subclasses
    supply the two things that actually differ: what discovery enumerates,
    and which credential key names the chosen resource.
    """

    app_key = META_APP

    #: The capability set every Meta channel shares. Kept as a class
    #: attribute so ``WhatsAppConnector`` can add embedded signup to it
    #: without restating the other six.
    CAPABILITIES = frozenset(
        {
            Capability.OAUTH,
            Capability.AUTO_DISCOVERY,
            Capability.WEBHOOKS,
            Capability.SHARED_WEBHOOK,
            Capability.AUTOMATIC_WEBHOOK_REGISTRATION,
            Capability.HEALTH_CHECKS,
            Capability.MANUAL_CONFIGURATION,
        }
    )

    #: Copy and presentation, per subclass. The three differ in almost
    #: nothing else, which is the point of the family.
    category = ConnectorCategory.MESSAGING
    icon = ""
    resource_title_key = ""
    resource_empty_key = ""
    resource_multiple = False

    #: Preview, and the same for all three, because the thing that is unfinished
    #: is shared: ``authorize_url`` emits a dialog URL with a literal
    #: ``{app_id}`` in it and ``exchange`` is not implemented, so no customer
    #: can complete consent on any of them, and ``discover`` — which only runs
    #: on a grant — has therefore never run outside a test. Beta would say
    #: "feature-complete and being proven", and a connector advertising OAuth,
    #: auto-discovery and (for WhatsApp) embedded signup in its manifest while
    #: none of the three can execute is not feature-complete. The manual path
    #: is finished and does work, which is why this is Preview rather than
    #: nothing at all. Availability is the other axis and is set per
    #: installation; this field is only ever about the code.
    maturity: Maturity = Maturity.PREVIEW

    #: What this channel actually carries, per subclass, checked against the
    #: ``ChannelProvider`` that would carry it. See the module docstring.
    features: tuple[FeatureSupport, ...] = CORE_FEATURES

    @property
    def manifest(self) -> ConnectorManifest:
        """Built from the subclass's few points of difference.

        One builder rather than three literals: WhatsApp, Messenger and
        Instagram share a provider, a webhook model, a validation routine and
        a repair, so three near-identical manifests would be three places for
        the shared parts to drift.
        """
        name = self.channel_type
        return ConnectorManifest(
            channel_type=name,
            name_key=f"connect.{name}.name",
            description_key=f"connect.{name}.description",
            category=self.category,
            icon=self.icon or name,
            capabilities=self.CAPABILITIES,
            # Both, always. Consent where the installation holds an app;
            # the guided form where it does not — and the capability
            # resolution, not this list, is what decides which is offered.
            auth_methods=(AuthMethod.OAUTH, AuthMethod.CREDENTIALS),
            required_permissions=self.scopes,
            required_credentials=(
                CredentialSpec(
                    name=self.resource_credential,
                    kind="text",
                    label_key=f"connect.meta.{self.resource_credential}.label",
                    help_key=f"connect.meta.{self.resource_credential}.help",
                ),
                CredentialSpec(
                    name="access_token",
                    kind="secret",
                    label_key="connect.meta.accessToken.label",
                    help_key="connect.meta.accessToken.help",
                ),
                CredentialSpec(
                    name="webhook_secret",
                    kind="secret",
                    label_key="connect.meta.appSecret.label",
                    help_key="connect.meta.appSecret.help",
                    # Belongs in the column, not the credentials blob. Without
                    # it a hand-connected Meta channel has nothing to verify
                    # inbound signatures against, and every delivery fails a
                    # check nobody can see failing.
                    is_webhook_secret=True,
                ),
            ),
            required_resources=(
                ResourceSpec(
                    key=self.picker_group_key,
                    title_key=self.resource_title_key or self.picker_group_key,
                    empty_key=self.resource_empty_key or f"connect.{name}.noResources",
                    multiple=self.resource_multiple,
                ),
            ),
            verification_steps=(
                VerificationSpec(
                    key="connect.meta.check.permissions",
                    title_key="connect.meta.check.permissions.title",
                    codes=(
                        ValidationCode.OK,
                        ValidationCode.MISSING_PERMISSION,
                        # The manual path can arrive with nothing typed; the
                        # consent path can arrive with no grant. Same code,
                        # because to the customer both mean "we have no way
                        # to talk to Meta as you".
                        ValidationCode.MISSING_CREDENTIAL,
                        ValidationCode.INVALID_TOKEN,
                        ValidationCode.EXPIRED_CREDENTIALS,
                        ValidationCode.PROVIDER_UNREACHABLE,
                    ),
                ),
                VerificationSpec(
                    key="connect.meta.check.resource",
                    title_key="connect.meta.check.resource.title",
                    codes=(
                        ValidationCode.OK,
                        ValidationCode.NO_RESOURCE_SELECTED,
                        ValidationCode.RESOURCE_NOT_ELIGIBLE,
                        ValidationCode.BUSINESS_VERIFICATION_REQUIRED,
                        ValidationCode.ADVISORY,
                    ),
                ),
            ),
            repair_actions=(
                RepairAction(
                    id=REREGISTER_WEBHOOK,
                    title_key="connect.meta.repair.reregisterWebhook.title",
                    description_key="connect.meta.repair.reregisterWebhook.description",
                ),
            ),
            supported_features=self.features,
            documentation=(
                DocumentationLink(
                    key="connect.meta.docs.businessManager",
                    url="https://business.facebook.com/settings",
                ),
            ),
            maturity=self.maturity,
            versions=META_VERSIONS,
        )

    #: Which credential names the resource this connector connects to —
    #: ``phone_number_id``, ``page_id``, ``instagram_id``. The single line of
    #: difference that the transport providers already key off.
    resource_credential: str = ""

    #: Scopes this channel needs. The union across a template's channels is
    #: what one consent dialog asks for.
    scopes: tuple[str, ...] = ()

    #: Copy key describing what the customer is about to pick.
    picker_group_key: str = ""

    # --- Authenticate -------------------------------------------------

    def credential_fields(self) -> tuple[Field, ...]:
        """The path for an installation with no app, and the fallback when
        consent is unavailable.

        Deliberately still guided: every field carries a help key explaining
        where in Meta's dashboard the value is, so even the manual path does
        not send the customer to Meta's documentation. It is a worse
        experience than OAuth, not an abandonment.
        """
        return (
            Field(
                name=self.resource_credential,
                kind="text",
                label_key=f"connect.meta.{self.resource_credential}.label",
                help_key=f"connect.meta.{self.resource_credential}.help",
            ),
            Field(
                name="access_token",
                kind="secret",
                label_key="connect.meta.accessToken.label",
                help_key="connect.meta.accessToken.help",
            ),
        )

    async def authorize_url(self, *, state: str, context: DeploymentContext) -> str:
        """Where the customer goes to consent.

        The redirect URI is derived from the installation's own base URL and
        never accepted from a caller: a client-supplied redirect is an open
        redirect, and an open redirect on an OAuth callback is token theft.
        """
        redirect = f"{context.public_base_url.rstrip('/')}/api/v1/channel-oauth/meta/callback"
        scopes = ",".join(self.scopes)
        return (
            f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
            f"?client_id={{app_id}}&redirect_uri={redirect}&state={state}&scope={scopes}"
        )

    # --- Discover -----------------------------------------------------

    async def _granted_scopes(self, token: str) -> frozenset[str]:
        """What the customer actually approved.

        Meta lets a customer decline individual scopes in the consent dialog
        and returns a token regardless, so a grant that looks successful can
        be missing exactly the permission the channel needs. Asking is the
        only way to find out before the first message fails to send.
        """
        body = await _graph("debug_token", token=token, params={"input_token": token})
        data = body.get("data", {})
        return frozenset(data.get("scopes", []) or [])

    # --- Verify -------------------------------------------------------

    def _credential_fix(self, attempt: Attempt) -> Fix:
        """How this customer fixes the credential they arrived with.

        The two paths fail differently and the console has to offer different
        buttons. Consent produced the token, so asking for consent again is
        the fix; a token that was *typed* is fixed by typing a better one, and
        offering "reauthorize" for it renders a consent button on an
        installation that may hold no Meta app at all — a button that goes
        nowhere, which is precisely why ``FIX_REENTER`` exists.

        ``attempt.grant`` is what tells them apart, and it is the distinction
        the previous signature could not make: it called the typed values
        "grant" too.
        """
        return Fix(kind=FIX_REAUTHORIZE) if attempt.grant else Fix(kind=FIX_REENTER)

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        """The Permissions Check, in the customer's terms.

        Every outcome here replaces something that would otherwise surface as
        a raw Graph error at the worst possible moment — the first time a
        customer message arrives and nothing happens.

        Reads ``attempt.credentials`` rather than ``attempt.grant``, so the
        same checks run on a token that was pasted into the form. Under the
        old signature they could not: the form path put nothing in ``grant``,
        so every check either probed an empty dict or was skipped, and the
        manual path — the only path on an installation with no Meta app —
        reached the summary screen entirely unverified.
        """
        token = str(attempt.credentials.get("access_token", ""))
        outcomes: list[ValidationResult] = []

        if not token:
            return (
                ValidationResult(
                    ValidationCode.MISSING_CREDENTIAL,
                    channel_type=self.channel_type,
                    params={"check": "meta.check.noGrant"},
                ),
            )

        try:
            granted = await self._granted_scopes(token)
        # Transport failures too, not only Graph's own errors. The contract
        # says check() returns outcomes and never raises, and a DNS failure or
        # a newline pasted into a token would otherwise surface as a 500 in
        # the middle of the Verify step — the one place the customer is being
        # told what is wrong with their setup.
        except (MetaError, httpx.HTTPError, httpx.InvalidURL) as exc:
            return (
                ValidationResult(
                    ValidationCode.INVALID_TOKEN,
                    channel_type=self.channel_type,
                    params={"detail": str(exc)},
                ),
            )

        missing = [scope for scope in self.scopes if scope not in granted]
        if missing:
            # Declining a scope is a normal thing to do by accident in Meta's
            # dialog, and the only honest fix is to ask again — so the check
            # names the permission rather than saying "permissions missing".
            # A pasted token is missing permissions for a different reason (it
            # was minted without them) and gets a different button.
            outcomes.append(
                ValidationResult(
                    ValidationCode.MISSING_PERMISSION,
                    channel_type=self.channel_type,
                    params={"scopes": ", ".join(missing)},
                )
            )
        else:
            outcomes.append(ValidationResult(ValidationCode.OK, channel_type=self.channel_type))

        selection = attempt.selection
        if not selection and not str(attempt.inputs.get(self.resource_credential, "")):
            # Nothing picked *and* nothing typed. The old signature saw only
            # the selection, so every manual connection — which names its
            # resource on the form and picks nothing — failed this check and
            # was blocked from connecting by the one step meant to unblock it.
            outcomes.append(
                ValidationResult(
                    ValidationCode.NO_RESOURCE_SELECTED,
                    channel_type=self.channel_type,
                )
            )

        for resource in selection:
            if resource.unavailable_reason:
                outcomes.append(
                    ValidationResult(
                        ValidationCode.RESOURCE_NOT_ELIGIBLE,
                        channel_type=self.channel_type,
                        params={
                            "resource": resource.label,
                            "reason": resource.unavailable_reason,
                        },
                        instructions_key=(f"connect.meta.fix.{resource.unavailable_reason}"),
                    )
                )

        return tuple(outcomes)

    # --- Connect ------------------------------------------------------

    # No ``register_webhook`` here, deliberately: Meta's callback URL is
    # configured once on the *app*, so there is no per-channel URL to register
    # and the base's "not_supported" is the honest answer. ``_subscribe`` is a
    # different operation that is easy to mistake for it — it points the
    # already-configured app at a resource, it does not register a URL — and
    # it is why ``AUTOMATIC_WEBHOOK_REGISTRATION`` is still declared: the
    # customer pastes nothing anywhere either way.

    async def _subscribe(self, node_id: str, token: str, fields: str) -> None:
        """Point the app's webhook at this resource.

        The customer never sees this, which is the point — it is the step
        that used to mean pasting a callback URL and a verify token into
        Meta's dashboard and hoping.
        """
        await _graph(
            f"{node_id}/subscribed_apps",
            token=token,
            method="POST",
            params={"subscribed_fields": fields},
        )

    #: Which events to ask Meta to send. Per subclass, because a Page and a
    #: WhatsApp number emit different things.
    subscribed_fields: str = "messages"

    #: Whether the app is subscribed on something other than the resource this
    #: channel's credentials name — the WABA behind a WhatsApp number, the
    #: Page behind an Instagram account. A restatement of what ``discover``
    #: puts in ``subscribe_on``, in the one form ``repair`` and certification
    #: can read: they are handed credentials, and the parent id lives in the
    #: ``external_parent_id`` column, which neither is given. False here is
    #: Messenger's case, where the Page *is* the subscription node.
    subscribes_on_parent: bool = False

    async def connect(self, *, company_id: UUID, attempt: Attempt) -> tuple[Connection, ...]:
        """Subscribe the app to each resource, and hand back what to store.

        Manual and OAuth converge here deliberately: a channel connected by
        hand and one connected by consent must be indistinguishable
        afterwards, or every later feature has to handle two shapes.

        The two paths are told apart by ``attempt.selection`` — what the
        picker produced — and each then reads only what its own path filled
        in. Nothing here has to guess which step a value came from.
        """
        if not attempt.selection:
            # The form path names its resource in the form rather than by
            # picking it from a list, so the typed values *are* the
            # credentials: ``inputs``, never ``grant``.
            # Whitelisted against the fields this connector actually
            # declared, never the raw submission: whatever a console posts
            # here is encrypted and kept forever, and the pydantic credential
            # schemas ignore extras, so nothing downstream would ever object.
            declared = {field.name for field in self.credential_fields()}
            inputs = {
                key: value
                for key, value in attempt.inputs.items()
                if key in declared or key == "webhook_secret"
            }
            resource_id = str(inputs.get(self.resource_credential, ""))
            if not resource_id:
                raise MetaError("meta.error.noResource")
            # Manual channels keep their own App Secret: the installation has
            # no shared app to verify against. Taken *out* of the credentials
            # on the way to its column — a secret stored in both places has
            # two sources of truth and only one of them is ever read.
            secret = inputs.pop("webhook_secret", None)
            return (
                Connection(
                    channel_type=self.channel_type,
                    display_name=attempt.display_name or f"{self.channel_type}:{resource_id}",
                    credentials=inputs,
                    external_id=resource_id,
                    webhook_secret=str(secret) if secret else None,
                ),
            )

        # A selection can only have come from discovery, and discovery only
        # runs on a grant — so this branch reads the grant rather than
        # ``credentials``, and says so.
        token = str(attempt.grant.get("access_token", ""))
        # One name cannot describe three channels, so the customer's own name
        # is honoured only when there is exactly one thing to hang it on.
        chosen_name = attempt.display_name if len(attempt.selection) == 1 else ""
        connections: list[Connection] = []
        for resource in attempt.selection:
            # A Page token, where discovery found one — never the user token.
            # The user token is broader, longer-lived and would let a leaked
            # channel row act on everything the customer approved.
            resource_token = str(resource.context.get("access_token") or token)
            subscribe_on = str(resource.context.get("subscribe_on") or resource.id)
            await self._subscribe(subscribe_on, resource_token, self.subscribed_fields)
            connections.append(
                Connection(
                    channel_type=self.channel_type,
                    display_name=chosen_name or resource.label,
                    credentials={
                        self.resource_credential: resource.id,
                        "access_token": resource_token,
                    },
                    external_id=resource.id,
                    external_parent_id=resource.context.get("parent_id"),
                    # None: the installation's app secret verifies inbound
                    # events, so there is nothing per-channel to store.
                    webhook_secret=None,
                )
            )
        return tuple(connections)

    # --- Diagnose -----------------------------------------------------

    async def diagnose(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> DiagnosticReport:
        """The four keys Graph will actually answer, and not one more.

        ``GET /debug_token`` carries three of them: whether the stored token
        is still valid and when it stops being (``AUTHENTICATION``), which of
        this channel's scopes were really granted rather than declined in the
        consent dialog (``PERMISSIONS``), and — by having succeeded against a
        versioned path at all — that the Graph version this connector targets
        is still being served (``API_VERSION``). ``GET /{node}/subscribed_apps``
        answers the fourth: whether Meta still sends this resource's events to
        our app (``WEBHOOK_STATUS``).

        The other six are left for the platform, which is better placed to
        answer all of them from what it recorded. ``RATE_LIMITS`` is the
        omission worth defending: Graph reports usage in an ``X-App-Usage``
        header scoped to the *app*, and under a shared app that budget is
        spent by every tenant on this installation at once. Charging it to
        whichever channel a support engineer happened to open would be a
        number that reads as per-channel and is not, which is a worse answer
        than the honest ``UNKNOWN`` the platform fills in.

        Never raises, and never guesses. Every branch below either measures
        something or omits the row. The one distinction it works hardest to
        keep is Graph *rejecting* the credential (a ``FAIL`` against the
        credential) versus Graph not answering at all (``UNKNOWN``) — during a
        Meta outage the second dressed up as the first would have a support
        engineer rotating a token that was fine.
        """
        token = str(credentials.get("access_token", ""))
        if not token:
            # Nothing to ask with. Reported rather than skipped: a channel row
            # with no token is a real and findable fault, and "not measured"
            # would hide it behind the same grey dash as an outage.
            return DiagnosticReport(
                channel_type=self.channel_type,
                items=(
                    Diagnostic(
                        key=DiagnosticKey.AUTHENTICATION,
                        status=DiagnosticStatus.FAIL,
                        detail_key="meta.diagnostic.authentication.missing",
                    ),
                ),
            )

        node = str(credentials.get(self.resource_credential, ""))
        # Concurrently, because they are independent and the report has a
        # twelve-second budget it shares with the platform's half.
        token_probe, subscription_probe = await asyncio.gather(
            _probe("debug_token", token=token, params={"input_token": token}),
            self._subscription_probe(node=node, token=token),
        )

        data = self._token_data(token_probe)
        items: list[Diagnostic] = [
            *self._authentication(token_probe, data),
            *self._permissions(data),
            self._api_version(token_probe),
        ]
        subscription = self._webhook_status(subscription_probe, data)
        if subscription is not None:
            items.append(subscription)
        return DiagnosticReport(channel_type=self.channel_type, items=tuple(items))

    async def _subscription_probe(self, *, node: str, token: str) -> _Probe | None:
        """Whether Meta still delivers this resource's events to our app.

        ``None`` when there is no node to ask about, which is a different
        thing from a failed call and produces no row rather than a red one.

        The limitation ``repair`` documents applies here for the same reason:
        ``connect`` subscribes on the *parent* — the WABA behind a WhatsApp
        number, the Page behind an Instagram account — and that id lives in
        the ``external_parent_id`` column, which ``diagnose`` is not given.
        So on those two this addresses a node that has no ``subscribed_apps``
        edge, Graph says so, and the answer comes back unmeasured. That is the
        intended outcome: a cross against a webhook that is working would send
        somebody to re-register a subscription that was never broken.
        """
        if not node:
            return None
        return await _probe(f"{node}/subscribed_apps", token=token)

    @staticmethod
    def _token_data(probe: _Probe) -> dict[str, Any] | None:
        """``debug_token``'s inner ``data`` object, or nothing readable."""
        if probe.body is None:
            return None
        data = probe.body.get("data")
        return data if isinstance(data, dict) else None

    def _authentication(self, probe: _Probe, data: dict[str, Any] | None) -> tuple[Diagnostic, ...]:
        """Does the stored credential still work, and for how much longer."""
        if not probe.reached:
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key="meta.diagnostic.providerUnreachable",
                    params={"detail": probe.detail},
                ),
            )
        if data is None:
            # Graph answered and would not tell us. That is about the
            # credential — an expired or revoked token is exactly what an
            # error envelope on ``debug_token`` looks like.
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    # Graph returns throttling and transient platform errors
                    # in the same envelope shape as a rejected credential.
                    # Reporting those as FAIL sends an engineer to rotate a
                    # token that works, which is precisely the failure this
                    # method exists to prevent — so a throttle is UNKNOWN:
                    # we learned nothing, rather than learned something bad.
                    status=(
                        DiagnosticStatus.UNKNOWN if _is_transient(probe) else DiagnosticStatus.FAIL
                    ),
                    detail_key=(
                        "meta.diagnostic.authentication.notAnswered"
                        if _is_transient(probe)
                        else "meta.diagnostic.authentication.rejected"
                    ),
                    params={"detail": probe.detail},
                ),
            )
        if not data.get("is_valid", False):
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.FAIL,
                    detail_key="meta.diagnostic.authentication.invalid",
                ),
            )

        expires_at = data.get("expires_at")
        if not isinstance(expires_at, int) or expires_at <= 0:
            # Meta reports a non-expiring token as zero. A Page token minted
            # from a long-lived user token is genuinely one of these, so this
            # is the common healthy case rather than a missing measurement.
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.OK,
                    detail_key="meta.diagnostic.authentication.longLived",
                ),
            )
        try:
            expiry = datetime.fromtimestamp(expires_at, tz=UTC)
        except (OverflowError, OSError, ValueError):
            # A timestamp too large for the platform's clock raises rather
            # than returning something wrong — and this runs *outside* any
            # caller's guard, so it would take the connector's entire half of
            # the report with it and leave four rows silently blank. Graph
            # should never send one; a report that loses four rows because it
            # did is a worse failure than a row that says so.
            return (
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key="meta.diagnostic.authentication.unreadableExpiry",
                ),
            )
        remaining = expiry - datetime.now(UTC)
        # Rounded up, so a token with twenty hours left says "1 day" rather
        # than "0 days" — which reads as a bug, not as urgency.
        days = max(math.ceil(remaining / timedelta(days=1)), 0)
        if remaining <= timedelta(0):
            status, detail_key = (
                DiagnosticStatus.FAIL,
                "meta.diagnostic.authentication.expired",
            )
        elif remaining <= timedelta(days=EXPIRY_WARNING_DAYS):
            status, detail_key = (
                DiagnosticStatus.WARN,
                "meta.diagnostic.authentication.expiring",
            )
        else:
            status, detail_key = DiagnosticStatus.OK, "meta.diagnostic.authentication.valid"
        return (
            Diagnostic(
                key=DiagnosticKey.AUTHENTICATION,
                status=status,
                value=expiry.isoformat(),
                detail_key=detail_key,
                params={"days": str(days)},
            ),
        )

    def _permissions(self, data: dict[str, Any] | None) -> tuple[Diagnostic, ...]:
        """Which of this channel's scopes the customer actually granted.

        Both lists are read, because they answer different halves of the same
        question: ``scopes`` is what was approved, ``granular_scopes`` is what
        was approved *and* attached to at least one business asset. A scope
        present in neither was declined in the dialog, which Meta permits and
        then hands back a working-looking token for — the failure this row
        exists to catch, since it surfaces otherwise as the first customer
        message going nowhere.

        No row at all when ``debug_token`` did not answer: the scopes are not
        derivable from anything stored, and an assumed ``OK`` here is the
        fabrication that would make the panel worse than nothing.
        """
        if data is None:
            return ()
        granted = {str(scope) for scope in data.get("scopes") or []}
        for entry in data.get("granular_scopes") or []:
            if isinstance(entry, dict) and entry.get("scope"):
                granted.add(str(entry["scope"]))
        missing = [scope for scope in self.scopes if scope not in granted]
        value = f"{len(self.scopes) - len(missing)}/{len(self.scopes)}"
        if missing:
            return (
                Diagnostic(
                    key=DiagnosticKey.PERMISSIONS,
                    status=DiagnosticStatus.FAIL,
                    value=value,
                    detail_key="meta.diagnostic.permissions.missing",
                    # No ``repair_action``: the only repair these connectors
                    # declare re-subscribes a webhook, and a declined scope is
                    # fixed by consenting again, which is the wizard's job and
                    # not a button this panel can honestly offer.
                    params={"scopes": ", ".join(missing)},
                ),
            )
        return (
            Diagnostic(
                key=DiagnosticKey.PERMISSIONS,
                status=DiagnosticStatus.OK,
                value=value,
            ),
        )

    @staticmethod
    def _api_version(probe: _Probe) -> Diagnostic:
        """That Meta is still serving the Graph version this code calls.

        Measured rather than recited. ``GRAPH_VERSION`` is in the path of the
        call that just succeeded, so a clean answer proves the version is
        live; anything else leaves the status ``UNKNOWN`` while still naming
        the version, because "we target v21.0 and could not confirm it" is
        more use to a support engineer than an empty row. A version Meta had
        retired would come back as an error envelope, not as a payload, and
        so would never be reported ``OK``.
        """
        return Diagnostic(
            key=DiagnosticKey.API_VERSION,
            status=(DiagnosticStatus.OK if probe.body is not None else DiagnosticStatus.UNKNOWN),
            value=GRAPH_VERSION,
        )

    def _webhook_status(
        self, probe: _Probe | None, data: dict[str, Any] | None
    ) -> Diagnostic | None:
        """Whether *our* app is still subscribed, not merely some app.

        The app id comes from ``debug_token``, which reports the app the token
        belongs to. Matching on it is what makes an ``OK`` here worth
        printing: ``subscribed_apps`` lists every app receiving the node's
        events, so a non-empty list on its own says somebody is subscribed
        and not that we are.

        No row when either call came back unreadable — including the
        parent-node case above. An empty list is the one thing that needs no
        app id to interpret and is reported without one.

        ``value`` means the same thing on every branch: how many event fields
        *our* app is receiving. A row whose number changed meaning between
        statuses would be a row nobody could read at a glance, which is the
        only way this panel gets read.
        """
        if probe is None or probe.body is None:
            return None
        apps = probe.body.get("data")
        apps = [app for app in apps if isinstance(app, dict)] if isinstance(apps, list) else []
        if not apps:
            return Diagnostic(
                key=DiagnosticKey.WEBHOOK_STATUS,
                status=DiagnosticStatus.FAIL,
                value="0",
                detail_key="meta.diagnostic.webhook.notSubscribed",
                repair_action=REREGISTER_WEBHOOK,
            )
        app_id = str(data.get("app_id", "")) if data else ""
        if not app_id:
            return None
        ours = [app for app in apps if str(app.get("id", "")) == app_id]
        if not ours:
            return Diagnostic(
                key=DiagnosticKey.WEBHOOK_STATUS,
                status=DiagnosticStatus.FAIL,
                value="0",
                detail_key="meta.diagnostic.webhook.otherAppSubscribed",
                params={"apps": str(len(apps))},
                repair_action=REREGISTER_WEBHOOK,
            )
        # Only checked when Graph volunteered the field list. Older Graph
        # responses omit it, and an empty list would otherwise read as "every
        # field is missing" on a subscription that is entirely healthy.
        subscribed = {str(name) for app in ours for name in app.get("subscribed_fields") or []}
        missing = (
            [name for name in self.subscribed_fields.split(",") if name not in subscribed]
            if subscribed
            else []
        )
        if missing:
            return Diagnostic(
                key=DiagnosticKey.WEBHOOK_STATUS,
                status=DiagnosticStatus.WARN,
                value=str(len(subscribed)),
                detail_key="meta.diagnostic.webhook.fieldsMissing",
                params={"fields": ", ".join(missing)},
                repair_action=REREGISTER_WEBHOOK,
            )
        return Diagnostic(
            key=DiagnosticKey.WEBHOOK_STATUS,
            status=DiagnosticStatus.OK,
            value=str(len(subscribed)) if subscribed else None,
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
        """Demonstrate one behaviour against Graph, or say why it could not.

        Everything below either measured something or reports that it did not.
        There is no branch that returns ``PASS`` from a shape check, a fixture
        or a credential being non-empty: a fabricated pass certifies a broken
        channel, and the administrator who reads it stops looking.

        No judgement about applicability or safety is made here, because the
        runner already made both. A scenario the manifest never claimed never
        arrives, and one that would message a customer arrives only with a
        target somebody typed on purpose — so a ``target`` in hand is
        permission to send, and this method uses it.

        The blanket ``except`` is not laziness about which errors are
        possible. The contract is a result and never a raise; the runner
        honours a raise by scoring the scenario ``FAIL`` with no evidence at
        all, and a ``FAIL`` carrying the redacted exception is the same
        outcome with something in it somebody can act on.
        """
        # The last guard in front of an irreversible call, and the reason it
        # is here rather than left to the runner: `target or ""` used to
        # convert None into an empty recipient and go to the wire anyway —
        # uploading a *persistent* attachment to the customer's Page before
        # the recipient was ever consulted. Graph rejected the empty
        # recipient, so nothing reached a thread, but a healthy channel
        # certified as broken and a reusable attachment id was minted on it.
        # Every sibling connector kept this guard; this is the one that
        # dropped it.
        if kind in EMITS_TO_A_CUSTOMER and not target:
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.SKIPPED,
                detail_key="meta.certification.skipped.noTarget",
            )
        try:
            return await self._scenario(
                kind, credentials=credentials, context=context, target=target
            )
        except Exception as exc:  # noqa: BLE001 - a connector reports; it never raises
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.FAIL,
                detail_key="meta.certification.unexpectedError",
                diagnostics={
                    "error": redact_credentials(f"{type(exc).__name__}: {exc}", credentials)
                },
            )

    async def _scenario(
        self,
        kind: ScenarioKind,
        *,
        credentials: dict[str, Any],
        context: DeploymentContext,
        target: str | None,
    ) -> ScenarioResult:
        """Which scenario is which. Split out so the guard above wraps all."""
        match kind:
            case ScenarioKind.AUTHENTICATION:
                return await self._certify_authentication(credentials=credentials, context=context)
            case ScenarioKind.WEBHOOK_DELIVERY:
                return await self._certify_webhook(credentials=credentials, context=context)
            # `target` is narrowed here rather than asserted: the caller's
            # guard already refused these three without one, and a type
            # checker that cannot see that is a type checker asking for the
            # guard to be stated twice — which is how one of them later gets
            # removed as redundant.
            case ScenarioKind.SEND_MESSAGE if target:
                return await self._certify_send(credentials=credentials, target=target)
            case ScenarioKind.MEDIA_UPLOAD if target:
                return await self._certify_media(credentials=credentials, target=target)
            case ScenarioKind.TYPING_INDICATOR if target:
                return await self._certify_typing(credentials=credentials, target=target)
            case ScenarioKind.RECONNECT:
                return await self._certify_reconnect(credentials=credentials)
            case ScenarioKind.TOKEN_REFRESH:
                return self._certify_token_refresh(context=context)
            case (
                ScenarioKind.RECEIVE_MESSAGE
                | ScenarioKind.MEDIA_DOWNLOAD
                | ScenarioKind.READ_RECEIPT
                | ScenarioKind.DISCONNECT
            ):
                return self._unexecutable(kind)
        # A scenario kind added after this connector was written. Saying so is
        # the honest answer; guessing at it would be the dishonest one.
        return _skipped(kind, "certification.notImplemented")

    def _unexecutable(self, kind: ScenarioKind) -> ScenarioResult:
        """The scenarios these connectors claim and genuinely cannot run.

        Four of them, and every one is a place where a plausible-looking pass
        was available and would have been a lie:

        - **RECEIVE_MESSAGE.** Nothing in Graph makes an inbound message
          appear; only a customer can. The tempting version feeds a saved
          webhook payload through the parser and calls it a pass — which
          certifies our fixture, not the channel, and would go on passing
          after Meta changed the envelope.
        - **MEDIA_DOWNLOAD.** Needs the media id (WhatsApp) or CDN URL
          (Messenger, Instagram) that only an inbound message carries. It is
          possible to upload our own file and read it back, and that would
          prove nothing about the case that actually breaks: reading media
          somebody *else* sent, which is where the permission failures live.
        - **READ_RECEIPT.** WhatsApp marks one specific inbound message read,
          so it needs a ``wamid``. The target is a recipient identity, not a
          message id, and reinterpreting it as one when it happens to look
          like a ``wamid`` would break the send scenario that reads the same
          field. One target means one thing.
        - **DISCONNECT.** There is no provider-side disconnect here to run. A
          Meta channel is disconnected by removing it from Blink Engage;
          deleting the app subscription is the webhook, which is
          ``RECONNECT``'s business, and doing it under the name "disconnect"
          would leave a live channel dark to prove a point nobody asked for.

        All four cost coverage and none costs score, which is exactly the
        trade the outcome vocabulary was built to express.
        """
        return _skipped(kind, _UNEXECUTABLE[kind])

    async def _certify_authentication(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> ScenarioResult:
        """``debug_token``, via ``diagnose`` rather than beside it.

        The same call, through the same method, so the certification report
        and the diagnostics panel cannot disagree about one token. A second
        copy of this would drift — and the first symptom would be a channel
        certified ``PRODUCTION_READY`` with a red authentication row on the
        panel next to it.

        It costs the subscription probe ``diagnose`` issues concurrently, so
        this scenario's duration is the pair rather than the token read alone.
        A slightly pessimistic number is a better trade than two
        implementations of the same measurement.

        Missing permissions turn a pass into a warning. The token is genuinely
        valid — that is what was measured — but a Meta token can authenticate
        perfectly and still be missing the scope the first outbound message
        needs, and with no target the send scenario is skipped and nothing
        else would catch it. "It worked, with something worth saying" is what
        ``WARNING`` is for.
        """
        kind = ScenarioKind.AUTHENTICATION
        report = await self.diagnose(credentials=credentials, context=context)
        item = report.get(DiagnosticKey.AUTHENTICATION)
        if item is None:  # pragma: no cover - diagnose always answers this key
            return _skipped(kind, "certification.skipped.notMeasured")

        outcome = _OUTCOME_OF_STATUS[item.status]
        detail_key = item.detail_key
        params = dict(item.params)
        diagnostics = {"authentication": item.status.value}
        if item.value:
            diagnostics["expires_at"] = item.value

        permissions = report.get(DiagnosticKey.PERMISSIONS)
        if permissions is not None:
            diagnostics["permissions"] = permissions.value or permissions.status.value
            if outcome is Outcome.PASS and permissions.status is DiagnosticStatus.FAIL:
                outcome = Outcome.WARNING
                detail_key = permissions.detail_key
                params = dict(permissions.params)
        return ScenarioResult(
            kind=kind,
            outcome=outcome,
            detail_key=detail_key,
            params=params,
            diagnostics=diagnostics,
        )

    async def _certify_webhook(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> ScenarioResult:
        """Whether Meta is still pointed at us for this resource.

        What is measurable from here is the subscription — that Meta will send
        this resource's events to *our* app, matched on the app id
        ``debug_token`` reports — and not a delivery. Nothing a connector can
        call makes Meta post an event on demand, so the pass carries a detail
        key naming what was actually established rather than letting
        "webhook delivery: pass" be read as "an event arrived".

        No row at all is a skip, not a failure, and for two of the three
        channels it is the expected answer: the app is subscribed on the WABA
        or the Page, whose id lives in a column certification is not handed.
        Failing that would send somebody to repair a subscription that was
        never broken — the same limitation ``repair`` documents, with the same
        resolution.
        """
        kind = ScenarioKind.WEBHOOK_DELIVERY
        report = await self.diagnose(credentials=credentials, context=context)
        item = report.get(DiagnosticKey.WEBHOOK_STATUS)
        if item is None:
            if self.subscribes_on_parent:
                return _skipped(
                    kind,
                    "certification.skipped.subscriptionNodeUnknown",
                    node_credential=self.resource_credential,
                )
            return _skipped(kind, "certification.skipped.notMeasured")

        outcome = _OUTCOME_OF_STATUS[item.status]
        return ScenarioResult(
            kind=kind,
            outcome=outcome,
            detail_key=(
                item.detail_key
                or ("meta.certification.webhook.subscribed" if outcome is Outcome.PASS else None)
            ),
            params=dict(item.params),
            diagnostics={"subscribed_fields": item.value or "0"},
        )

    async def _certify_send(self, *, credentials: dict[str, Any], target: str) -> ScenarioResult:
        """A real message, through the request the transport would build.

        Not a dry run and not a permissions inference: the Send API is where
        this channel actually fails, and it fails for reasons — a token
        without ``pages_messaging``, a number the business account no longer
        owns — that every earlier check passes cleanly.
        """
        kind = ScenarioKind.SEND_MESSAGE
        node, token = self._node_and_token(credentials)
        if not node or not token:
            return _skipped(kind, "certification.skipped.credentialsIncomplete")

        sent = await self._send_text_call(
            node=node, token=token, target=target, body=CERTIFICATION_MESSAGE
        )
        refused = _refusal(kind, sent, failure_key="meta.certification.sendFailed")
        if refused is not None:
            return refused
        return self._delivered(kind, sent)

    async def _certify_media(self, *, credentials: dict[str, Any], target: str) -> ScenarioResult:
        """Upload an image to Meta, then send it — both halves, in order.

        The upload alone would pass on a channel that cannot deliver: they are
        different endpoints with different failure modes, and Instagram in
        particular takes attachments on a path Messenger's upload does not
        feed. Since the runner only reaches this with a deliberate target,
        proving the whole path is what the opt-in bought.
        """
        kind = ScenarioKind.MEDIA_UPLOAD
        node, token = self._node_and_token(credentials)
        if not node or not token:
            return _skipped(kind, "certification.skipped.credentialsIncomplete")

        upload = await self._upload_media_call(node=node, token=token)
        refused = _refusal(kind, upload, failure_key="meta.certification.uploadFailed")
        if refused is not None:
            return refused
        media_id = self._uploaded_media_id(upload.body or {})
        if not media_id:
            # A clean answer with nothing to send. The transport would raise a
            # KeyError here on the next customer's attachment.
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.FAIL,
                detail_key="meta.certification.noMediaId",
                diagnostics=_evidence(upload),
            )

        sent = await self._send_media_call(node=node, token=token, target=target, media_id=media_id)
        refused = _refusal(
            kind,
            sent,
            failure_key="meta.certification.mediaSendFailed",
            extra={"media_id": media_id},
        )
        if refused is not None:
            return refused
        return self._delivered(kind, sent, extra={"media_id": media_id})

    async def _certify_typing(self, *, credentials: dict[str, Any], target: str) -> ScenarioResult:
        """Turn the typing indicator on, then off again.

        The second call is not part of the measurement — the outcome is
        decided by the first — but a certification run should not leave a
        "typing…" bubble sitting in somebody's thread, and whether it managed
        to clear it is worth recording either way.
        """
        kind = ScenarioKind.TYPING_INDICATOR
        node, token = self._node_and_token(credentials)
        if not node or not token:
            return _skipped(kind, "certification.skipped.credentialsIncomplete")

        started = await self._typing_call(node=node, token=token, target=target, on=True)
        refused = _refusal(kind, started, failure_key="meta.certification.typingFailed")
        if refused is not None:
            return refused
        cleared = await self._typing_call(node=node, token=token, target=target, on=False)
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.PASS,
            diagnostics={
                **_evidence(started),
                "cleared": "true" if cleared.body is not None else "false",
            },
        )

    async def _certify_reconnect(self, *, credentials: dict[str, Any]) -> ScenarioResult:
        """Re-subscribe the app — the exact call the one-click repair makes.

        Through ``_subscribe`` rather than beside it, so what certification
        proves and what the repair button does are the same request. Safe to
        run on a working channel: re-subscribing an already-subscribed app is
        Meta's own no-op, which is why this needs no prior disconnect and why
        running it does not leave the channel anywhere it was not already.

        Skipped where the subscription lives on the parent node, for the
        reason ``_certify_webhook`` gives: the id is in a column this is not
        handed, and subscribing the wrong node would fail a channel that
        works.
        """
        kind = ScenarioKind.RECONNECT
        if self.subscribes_on_parent:
            return _skipped(
                kind,
                "certification.skipped.subscriptionNodeUnknown",
                node_credential=self.resource_credential,
            )
        node, token = self._node_and_token(credentials)
        if not node or not token:
            return _skipped(kind, "certification.skipped.credentialsIncomplete")

        try:
            await self._subscribe(node, token, self.subscribed_fields)
        except MetaError as exc:
            # Already redacted by ``_graph``, which puts the token through
            # ``redact_credentials`` before it ever reaches an exception.
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.FAIL,
                detail_key="meta.certification.subscribeFailed",
                diagnostics={"detail": str(exc)},
            )
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            return _skipped(
                kind,
                "certification.skipped.providerUnreachable",
                detail=redact_credentials(str(exc), {"access_token": token}),
            )
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.PASS,
            diagnostics={"node": node, "subscribed_fields": self.subscribed_fields},
        )

    def _certify_token_refresh(self, *, context: DeploymentContext) -> ScenarioResult:
        """Meta long-lived tokens can be exchanged. This cannot exchange them.

        Two things are missing and only one of them is code. The exchange is
        ``GET /oauth/access_token?grant_type=fb_exchange_token``, which needs
        the app id and app secret — and ``run_scenario`` is handed channel
        credentials and a ``DeploymentContext`` that says *whether* an app is
        configured, never what it is. On top of that ``exchange`` is not
        implemented on this connector at all, which is the same unfinished
        half that makes these three ``PREVIEW``.

        So this reports what it found rather than running anything, and both
        facts go in ``diagnostics`` because they are the two separate things
        that would have to change. Attempting the call with credentials we do
        not have, in order to produce a ``FAIL``, would report a connector
        that never claimed to refresh tokens as one that tried and broke.
        """
        implemented = type(self).exchange is not Connector.exchange
        return ScenarioResult(
            kind=ScenarioKind.TOKEN_REFRESH,
            outcome=Outcome.SKIPPED,
            detail_key=(
                "certification.skipped.noAppCredentials"
                if implemented
                else "certification.skipped.tokenExchangeUnimplemented"
            ),
            diagnostics={
                "exchange_implemented": str(implemented).lower(),
                "app_configured": str(context.has_app(self.app_key)).lower(),
            },
        )

    # The Graph calls each scenario makes. Everything below is the Messenger
    # Platform's Send API — the shape ``providers/_meta_messaging.py`` uses,
    # shared by Messenger and Instagram for the same reason it is shared
    # there. WhatsApp's Cloud API agrees with it on the host and nothing else,
    # so ``WhatsAppConnector`` overrides every one of them.
    #
    # Authentication travels as a parameter rather than the Bearer header the
    # WhatsApp transport uses. Graph accepts either, and every other call in
    # this module already uses the parameter — one convention here means one
    # place where redaction has to be right.

    def _node_and_token(self, credentials: dict[str, Any]) -> tuple[str, str]:
        """The resource this channel sends from, and what it sends with."""
        return (
            str(credentials.get(self.resource_credential, "")),
            str(credentials.get("access_token", "")),
        )

    def _delivered(
        self, kind: ScenarioKind, sent: _Probe, *, extra: dict[str, str] | None = None
    ) -> ScenarioResult:
        """A send Graph accepted, graded on whether it can be evidenced.

        A 200 with no message id in it is not quite a pass: the transport
        reads that field to record what it sent, so a body without one is a
        message we cannot point at afterwards. It went, which is why this is a
        warning rather than a failure.
        """
        diagnostics = {**_evidence(sent), **(extra or {})}
        message_id = self._sent_message_id(sent.body or {})
        if not message_id:
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.WARNING,
                detail_key="meta.certification.noMessageId",
                diagnostics=diagnostics,
            )
        return ScenarioResult(
            kind=kind, outcome=Outcome.PASS, diagnostics={**diagnostics, "message_id": message_id}
        )

    async def _send_text_call(self, *, node: str, token: str, target: str, body: str) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/messages",
            token=token,
            payload={"recipient": {"id": target}, "message": {"text": body}},
            timeout=CERTIFICATION_TIMEOUT,
        )

    async def _upload_media_call(self, *, node: str, token: str) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/message_attachments",
            token=token,
            form={
                "message": json.dumps(
                    {"attachment": {"type": "image", "payload": {"is_reusable": True}}}
                )
            },
            files={
                "filedata": (
                    CERTIFICATION_IMAGE_NAME,
                    CERTIFICATION_IMAGE,
                    CERTIFICATION_IMAGE_TYPE,
                )
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    async def _send_media_call(
        self, *, node: str, token: str, target: str, media_id: str
    ) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/messages",
            token=token,
            payload={
                "recipient": {"id": target},
                "message": {
                    "attachment": {"type": "image", "payload": {"attachment_id": media_id}}
                },
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    async def _typing_call(self, *, node: str, token: str, target: str, on: bool) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/messages",
            token=token,
            payload={
                "recipient": {"id": target},
                "sender_action": "typing_on" if on else "typing_off",
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    @staticmethod
    def _uploaded_media_id(body: dict[str, Any]) -> str:
        return str(body.get("attachment_id", "") or "")

    @staticmethod
    def _sent_message_id(body: dict[str, Any]) -> str:
        return str(body.get("message_id", "") or "")

    def supported_until(self) -> date | None:
        """When Meta stops serving the Graph version this connector speaks.

        A real date, because Meta genuinely publishes one — each version
        retires roughly two years after its successor ships, listed per
        version in Meta's changelog — and ``None`` here would throw away the
        one piece of information the field exists to carry. v21.0 retires on
        2027-01-21, so an installation on this connector starts being flagged
        as expiring in late October 2026, which is when a migration should
        start rather than when it becomes urgent.

        The date is looked up by version rather than returned as a constant,
        so bumping ``GRAPH_VERSION`` without re-reading Meta's table answers
        ``None`` instead of the previous version's retirement date. That
        matters more than it sounds: an administrator schedules work around
        this, and a confidently wrong date schedules the wrong work.
        """
        return GRAPH_VERSION_SUNSET.get(GRAPH_VERSION)

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
        """Re-subscribe the app to this channel's resource.

        ``webhook_secret`` and ``callback_url`` are accepted and unused, which
        is the honest shape for a shared-webhook connector: the secret is the
        installation's App Secret and the URL is configured once on the app,
        so there is nothing here that could rotate either. The returned
        ``Repair`` therefore leaves both alone — echoing the secret back would
        claim a column had been rewritten that was never touched, and that
        claim is exactly what the bare-dict return used to make by accident.

        Failures come back as ``repaired=False`` rather than as an exception:
        a repair that raises is a 500 the console cannot turn into a sentence,
        and "we could not re-subscribe" is a thing the customer can act on.
        """
        if action != REREGISTER_WEBHOOK:
            return Repair(repaired=False, reason="not_supported")

        # Known limit: ``connect`` subscribes on ``subscribe_on`` — the WABA
        # for a WhatsApp number, the Page for an Instagram account — and that
        # id lives in the ``external_parent_id`` column, which ``repair`` is
        # not given. So this can only re-subscribe on the resource's own id,
        # which is right for a Page and wrong for the other two; they come
        # back ``repaired=False`` from Graph rather than silently claiming a
        # subscription they did not make.
        node_id = str(credentials.get(self.resource_credential, ""))
        token = str(credentials.get("access_token", ""))
        if not node_id or not token:
            return Repair(repaired=False, reason="meta.repair.credentialsIncomplete")

        try:
            await self._subscribe(node_id, token, self.subscribed_fields)
        except MetaError:
            # The Graph detail is dropped on purpose: ``Repair.reason`` is a
            # code the console translates, and unlike ``CheckOutcome`` it
            # carries no params for a detail to travel in.
            return Repair(repaired=False, reason="meta.repair.subscribeFailed")
        return Repair(credentials=dict(credentials))


@ConnectorRegistry.register("whatsapp")
class WhatsAppConnector(MetaConnector):
    """WhatsApp Cloud API.

    Discovery is two hops rather than one: the grant names the business
    accounts, and the phone numbers hang off those. Worth the extra call —
    the phone number id is the single value a customer most often gets wrong
    when configuring WhatsApp by hand, because Meta's dashboard shows it
    beside a display number that is *not* it.
    """

    icon = "whatsapp"
    resource_title_key = "connect.whatsapp.resources.title"
    resource_empty_key = "connect.whatsapp.resources.empty"
    #: Read off ``providers/whatsapp.py``, which is stricter than Meta's
    #: product page in three places worth stating:
    #:
    #: - **No typing indicators.** ``typing_indicator`` returns ``None`` and
    #:   says why: the Cloud API exposes typing only as a side effect of
    #:   marking one specific inbound message read, which needs a message id
    #:   where the contract gives a thread id. Messenger and Instagram *do*
    #:   have it, which is exactly why claiming it here would be believed.
    #: - **No templates or interactive messages.** The connector subscribes to
    #:   ``message_template_status_update`` so it hears about approvals, but
    #:   ``send_message`` only ever builds ``type: text`` and media payloads —
    #:   there is no code path that sends a template or a button, and nothing
    #:   parses an inbound ``interactive`` reply. Both would be a lie today
    #:   and a one-line change to the transport away from being true.
    #: - **No edits or deletes.** Both provider methods are stubs, and the
    #:   Cloud API has neither for a business-sent message.
    #:
    #: What is real: text and media both ways (images, video, audio and
    #: documents, with the caption riding on the first attachment), read
    #: receipts outbound only — ``mark_as_read`` posts a genuine ``status:
    #: read`` for a customer's message, while the customer's own read
    #: receipts arrive on the status webhook that ``receive_message``
    #: deliberately skips — and threading both ways, since outbound sets
    #: ``context.message_id`` and inbound reads it back.
    features = (
        *CORE_FEATURES,
        FeatureSupport(ChannelFeature.MEDIA, Direction.BOTH),
        FeatureSupport(
            ChannelFeature.READ_RECEIPTS,
            Direction.OUTBOUND,
            note_key="connect.whatsapp.features.readReceipts",
        ),
        # INBOUND, not BOTH. The outbound half is unreachable:
        # ``ConversationService.send_reply`` populates
        # ``reply_to_external_message_id`` only for a provider declaring
        # ``supports_invisible_reply_threading``, and ``EmailProvider`` is
        # the only one in the codebase that does. The reply-reference code
        # in this provider is real and never called, so claiming BOTH
        # promises a customer a quoted reply the product cannot send.
        FeatureSupport(ChannelFeature.THREADING, Direction.INBOUND),
    )
    resource_credential = "phone_number_id"
    scopes = ("whatsapp_business_management", "whatsapp_business_messaging")
    picker_group_key = "connect.meta.group.whatsapp"
    subscribed_fields = "messages,message_template_status_update"
    #: The app is subscribed on the WABA, never on the phone number —
    #: ``discover`` puts the WABA in ``subscribe_on`` for exactly this reason.
    subscribes_on_parent = True

    CAPABILITIES = MetaConnector.CAPABILITIES | {Capability.EMBEDDED_SIGNUP}

    async def discover(self, *, grant: dict[str, Any]) -> tuple[Resource, ...]:
        token = str(grant.get("access_token", ""))
        if not token:
            return ()
        # The businesses this grant covers, then each one's numbers.
        debug = await _graph("debug_token", token=token, params={"input_token": token})
        granular = debug.get("data", {}).get("granular_scopes", []) or []
        waba_ids: list[str] = []
        for entry in granular:
            if entry.get("scope") == "whatsapp_business_management":
                waba_ids.extend(entry.get("target_ids", []) or [])

        resources: list[Resource] = []
        for waba_id in dict.fromkeys(waba_ids):
            body = await _graph(f"{waba_id}/phone_numbers", token=token)
            for number in body.get("data", []) or []:
                verification = number.get("code_verification_status")
                resources.append(
                    Resource(
                        id=str(number.get("id")),
                        label=str(
                            number.get("verified_name")
                            or number.get("display_phone_number")
                            or number.get("id")
                        ),
                        group_key=self.picker_group_key,
                        detail={
                            "number": str(number.get("display_phone_number", "")),
                            "quality": str(number.get("quality_rating", "")),
                        },
                        # Shown rather than filtered out: a customer who
                        # cannot find their number assumes we are broken.
                        unavailable_reason=(
                            None if verification == "VERIFIED" else "numberNotVerified"
                        ),
                        context={"parent_id": waba_id, "subscribe_on": waba_id},
                    )
                )
        return tuple(resources)

    # --- Certify ------------------------------------------------------
    #
    # The Cloud API's own shapes, read off ``providers/whatsapp.py``. It
    # shares a host with the Messenger Send API and nothing else: a different
    # recipient field, a different envelope, a different media endpoint and a
    # different place to find the id of what was sent. Certification sends
    # what the transport sends, so a pass means the exact request the product
    # makes on the next customer reply was accepted today.
    #
    # ``_typing_call`` is deliberately not among them. This channel does not
    # claim typing indicators — the Cloud API has no freestanding toggle — so
    # the runner never asks for that scenario, and inheriting the Messenger
    # shape means that if somebody ever adds the feature to the manifest
    # without adding it to the transport, certification fails it rather than
    # quietly passing.

    async def _send_text_call(self, *, node: str, token: str, target: str, body: str) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": target,
                "type": "text",
                "text": {"body": body},
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    async def _upload_media_call(self, *, node: str, token: str) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/media",
            token=token,
            form={"messaging_product": "whatsapp", "type": CERTIFICATION_IMAGE_TYPE},
            files={
                "file": (CERTIFICATION_IMAGE_NAME, CERTIFICATION_IMAGE, CERTIFICATION_IMAGE_TYPE)
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    async def _send_media_call(
        self, *, node: str, token: str, target: str, media_id: str
    ) -> _Probe:
        return await _attempt(
            "POST",
            f"{node}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": target,
                "type": "image",
                "image": {"id": media_id},
            },
            timeout=CERTIFICATION_TIMEOUT,
        )

    @staticmethod
    def _uploaded_media_id(body: dict[str, Any]) -> str:
        return str(body.get("id", "") or "")

    @staticmethod
    def _sent_message_id(body: dict[str, Any]) -> str:
        """The Cloud API answers with a list; the Send API with a field."""
        messages = body.get("messages")
        first = messages[0] if isinstance(messages, list) and messages else None
        return str(first.get("id", "") or "") if isinstance(first, dict) else ""


@ConnectorRegistry.register("messenger")
class MessengerConnector(MetaConnector):
    """Facebook Messenger.

    Discovery returns Pages, and each carries its own Page token — which is
    what gets stored. A Page token is scoped to one Page and survives the
    user token being revoked, so it is both the narrower credential and the
    more durable one.
    """

    icon = "messenger"
    category = ConnectorCategory.SOCIAL
    resource_title_key = "connect.messenger.resources.title"
    resource_empty_key = "connect.messenger.resources.empty"
    # A customer with four Pages usually wants all four.
    resource_multiple = True
    #: Read off ``providers/_meta_messaging.py``, which differs from WhatsApp
    #: in both directions:
    #:
    #: - **Typing indicators are real here.** ``typing_indicator`` posts a
    #:   ``sender_action`` of ``typing_on``/``typing_off``. Outbound only —
    #:   there is no such thing as receiving one.
    #: - **Read receipts are not.** ``mark_as_read`` is a stub, and says why:
    #:   ``mark_seen`` addresses a recipient id where the contract supplies a
    #:   message id. The mirror image of WhatsApp, and the reason neither
    #:   channel can inherit the other's row.
    #: - **Threading is inbound only.** ``_parse_messaging_item`` reads
    #:   ``message.reply_to.mid``, so an agent can see which message a
    #:   customer replied to; ``_send_text`` builds no reply reference, so the
    #:   agent cannot reply to one visibly. A single tick against "Threading"
    #:   would be read as both.
    #: - **Media carries a caveat.** The Send API has no combined text and
    #:   attachment message, so a reply with both arrives as two messages.
    #:   True support, qualified — which is what ``note_key`` is for.
    #:
    #: No edits or deletes: both provider methods are stubs.
    features = (
        *CORE_FEATURES,
        FeatureSupport(
            ChannelFeature.MEDIA,
            Direction.BOTH,
            note_key="connect.meta.features.mediaSeparateMessage",
        ),
        FeatureSupport(ChannelFeature.TYPING_INDICATORS, Direction.OUTBOUND),
        FeatureSupport(ChannelFeature.THREADING, Direction.INBOUND),
    )
    resource_credential = "page_id"
    scopes = ("pages_show_list", "pages_messaging", "pages_manage_metadata")
    picker_group_key = "connect.meta.group.pages"
    subscribed_fields = "messages,messaging_postbacks,messaging_optins,message_deliveries"

    async def discover(self, *, grant: dict[str, Any]) -> tuple[Resource, ...]:
        token = str(grant.get("access_token", ""))
        if not token:
            return ()
        body = await _graph(
            "me/accounts", token=token, params={"fields": "id,name,category,tasks,access_token"}
        )
        resources = []
        for page in body.get("data", []) or []:
            tasks = page.get("tasks", []) or []
            resources.append(
                Resource(
                    id=str(page.get("id")),
                    label=str(page.get("name") or page.get("id")),
                    group_key=self.picker_group_key,
                    detail={"category": str(page.get("category", ""))},
                    # A Page the customer administers but cannot message from
                    # is a real and confusing state; naming it is kinder than
                    # omitting the Page they are looking for.
                    unavailable_reason=None if "MESSAGING" in tasks else "noMessagingRights",
                    context={"access_token": page.get("access_token")},
                )
            )
        return tuple(resources)


@ConnectorRegistry.register("instagram")
class InstagramConnector(MetaConnector):
    """Instagram professional messaging.

    Rides the Page graph: an Instagram business account is reached through
    the Page it is linked to, and the token stored is that Page's. Discovery
    therefore enumerates Pages and keeps only those with a linked account,
    which also explains the empty-list case a customer hits most often —
    a personal Instagram account cannot be connected at all.
    """

    icon = "instagram"
    category = ConnectorCategory.SOCIAL
    resource_title_key = "connect.instagram.resources.title"
    resource_empty_key = "connect.instagram.resources.empty"
    resource_multiple = True
    #: The same transport as Messenger, so the same rows — with one
    #: narrowing. ``_send_attachments`` maps anything that is not an image,
    #: video or audio file to Meta's ``file`` attachment type, and Instagram
    #: messaging does not accept it: a customer attaching a PDF gets a
    #: rejected send. So media is real in both directions and qualified in
    #: one, and the note says which, rather than the matrix promising
    #: documents that will never arrive.
    features = (
        *CORE_FEATURES,
        FeatureSupport(
            ChannelFeature.MEDIA,
            Direction.BOTH,
            note_key="connect.instagram.features.mediaNoDocuments",
        ),
        FeatureSupport(ChannelFeature.TYPING_INDICATORS, Direction.OUTBOUND),
        FeatureSupport(ChannelFeature.THREADING, Direction.INBOUND),
    )
    resource_credential = "instagram_id"
    scopes = ("instagram_basic", "instagram_manage_messages", "pages_show_list")
    picker_group_key = "connect.meta.group.instagram"
    subscribed_fields = "messages,messaging_postbacks"
    #: Subscription happens on the linked Page, never on the Instagram account
    #: — the same fact ``discover`` records as ``subscribe_on``.
    subscribes_on_parent = True

    async def discover(self, *, grant: dict[str, Any]) -> tuple[Resource, ...]:
        token = str(grant.get("access_token", ""))
        if not token:
            return ()
        body = await _graph(
            "me/accounts",
            token=token,
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username}",
            },
        )
        resources = []
        for page in body.get("data", []) or []:
            account = page.get("instagram_business_account") or {}
            if not account.get("id"):
                continue
            resources.append(
                Resource(
                    id=str(account["id"]),
                    label=str(account.get("username") or account["id"]),
                    group_key=self.picker_group_key,
                    detail={"page": str(page.get("name", ""))},
                    context={
                        "access_token": page.get("access_token"),
                        "parent_id": str(page.get("id")),
                        # Subscription happens on the Page, not the Instagram
                        # account — one of the details that makes configuring
                        # this by hand so error-prone.
                        "subscribe_on": str(page.get("id")),
                    },
                )
            )
        return tuple(resources)

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        outcomes = list(await super().validate(attempt))
        # Not settable through any API, and the single most common reason a
        # correctly-connected Instagram channel receives nothing. A warning
        # rather than a failure: it is a toggle in the customer's phone, and
        # blocking the flow on something we cannot verify would strand them.
        outcomes.append(
            ValidationResult(
                ValidationCode.ADVISORY,
                channel_type=self.channel_type,
                params={"check": "meta.check.instagramMessageAccess"},
                instructions_key="connect.meta.fix.instagramInbox",
            )
        )
        return tuple(outcomes)


__all__ = [
    "InstagramConnector",
    "MessengerConnector",
    "MetaConnector",
    "META_APP",
    "WhatsAppConnector",
]
