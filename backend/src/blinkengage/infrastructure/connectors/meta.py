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
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    """One Graph read for diagnostics, classified rather than raised.

    ``reached`` is the distinction the whole report hangs on. Graph answering
    "this token is invalid" and Graph never answering at all collapse into one
    exception for ``_graph``'s callers, and that is right for them — the
    wizard tells a customer to try again either way. A diagnostics panel must
    keep them apart: reporting an unreachable provider as a credential failure
    sends a support engineer rotating a token that was never the problem,
    during an outage, while a customer waits.
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


async def _probe(path: str, *, token: str, params: dict[str, str] | None = None) -> _Probe:
    """A read that cannot fail, for a report that must not.

    Deliberately not ``_graph``: this needs the three things ``_graph``
    discards on its way to raising — whether the response came from Meta at
    all, whether the body was an error envelope or a payload, and the status
    code — and bending ``_graph`` to return them would change the behaviour
    ``validate``, ``connect`` and ``repair`` are written against. The URL and
    the timeout still come from the same constants, so the two paths cannot
    end up talking to different Graphs.
    """
    try:
        async with httpx.AsyncClient(timeout=DIAGNOSTIC_TIMEOUT) as client:
            response = await client.get(
                f"{GRAPH_BASE}/{GRAPH_VERSION}/{path.lstrip('/')}",
                params={**(params or {}), "access_token": token},
            )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # Never got there. The token is in the request, and httpx puts the
        # request in the exception, so this is redacted like everything else
        # that escapes this module.
        return _Probe(detail=redact_credentials(str(exc), {"access_token": token}))
    try:
        body = response.json()
    except ValueError:  # pragma: no cover - Graph always sends JSON
        return _Probe(reached=True, detail="unreadable")
    if not isinstance(body, dict):
        return _Probe(reached=True, detail="unreadable")
    error = body.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")) or "unknown"
        raw_code = error.get("code")
        return _Probe(
            reached=True,
            detail=redact_credentials(message, {"access_token": token}),
            error_code=raw_code if isinstance(raw_code, int) else None,
        )
    if response.status_code >= 400:
        return _Probe(reached=True, detail=str(response.status_code))
    return _Probe(body=body, reached=True)



#: Graph error codes that mean "ask again later", not "your credential is
#: wrong". 4/17/32/613 are rate limits of various kinds; 1 and 2 are
#: transient platform errors. They arrive in the same envelope as a genuine
#: rejection, and telling them apart is the difference between an engineer
#: waiting five minutes and an engineer rotating a working token.
_TRANSIENT_GRAPH_CODES = frozenset({1, 2, 4, 17, 32, 613})


def _is_transient(probe: object) -> bool:
    code = getattr(probe, "error_code", None)
    return isinstance(code, int) and code in _TRANSIENT_GRAPH_CODES

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
                        DiagnosticStatus.UNKNOWN
                        if _is_transient(probe)
                        else DiagnosticStatus.FAIL
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
