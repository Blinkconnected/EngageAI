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
"""

from __future__ import annotations

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
from blinkengage.domain.connectors import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    FIX_MANUAL,
    FIX_REAUTHORIZE,
    FIX_REENTER,
    Capability,
    CheckOutcome,
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


class MetaConnector(Connector):
    """Shared behaviour for the three Meta channels.

    Not registered itself — it has no channel type of its own. Subclasses
    supply the two things that actually differ: what discovery enumerates,
    and which credential key names the chosen resource.
    """

    app_key = META_APP

    declares = frozenset(
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

    async def check(self, attempt: Attempt) -> tuple[CheckOutcome, ...]:
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
        outcomes: list[CheckOutcome] = []

        if not token:
            return (
                CheckOutcome(
                    "meta.check.noGrant",
                    CHECK_FAIL,
                    fix=self._credential_fix(attempt),
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
                CheckOutcome(
                    "meta.check.tokenRejected",
                    CHECK_FAIL,
                    params={"detail": str(exc)},
                    fix=self._credential_fix(attempt),
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
                CheckOutcome(
                    "meta.check.scopesMissing",
                    CHECK_FAIL,
                    params={"scopes": ", ".join(missing)},
                    fix=self._credential_fix(attempt),
                )
            )
        else:
            outcomes.append(CheckOutcome("meta.check.scopesGranted", CHECK_OK))

        selection = attempt.selection
        if not selection and not str(attempt.inputs.get(self.resource_credential, "")):
            # Nothing picked *and* nothing typed. The old signature saw only
            # the selection, so every manual connection — which names its
            # resource on the form and picks nothing — failed this check and
            # was blocked from connecting by the one step meant to unblock it.
            outcomes.append(
                CheckOutcome(
                    "meta.check.nothingSelected",
                    CHECK_FAIL,
                    # On the form path the missing id is a value they type, so
                    # the fix is one step back. On the picker path there is
                    # nothing to type and no fix worth offering.
                    fix=None if attempt.grant else Fix(kind=FIX_REENTER),
                )
            )

        for resource in selection:
            if resource.unavailable_reason:
                outcomes.append(
                    CheckOutcome(
                        f"meta.check.{resource.unavailable_reason}",
                        CHECK_FAIL,
                        params={"resource": resource.label},
                        fix=Fix(
                            kind=FIX_MANUAL,
                            instructions_key=f"connect.meta.fix.{resource.unavailable_reason}",
                        ),
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

    async def connect(
        self, *, company_id: UUID, attempt: Attempt
    ) -> tuple[Connection, ...]:
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
                    display_name=attempt.display_name
                    or f"{self.channel_type}:{resource_id}",
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

    resource_credential = "phone_number_id"
    scopes = ("whatsapp_business_management", "whatsapp_business_messaging")
    picker_group_key = "connect.meta.group.whatsapp"
    subscribed_fields = "messages,message_template_status_update"

    declares = MetaConnector.declares | {Capability.EMBEDDED_SIGNUP}

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

    async def check(self, attempt: Attempt) -> tuple[CheckOutcome, ...]:
        outcomes = list(await super().check(attempt))
        # Not settable through any API, and the single most common reason a
        # correctly-connected Instagram channel receives nothing. A warning
        # rather than a failure: it is a toggle in the customer's phone, and
        # blocking the flow on something we cannot verify would strand them.
        outcomes.append(
            CheckOutcome(
                "meta.check.instagramMessageAccess",
                CHECK_WARN,
                fix=Fix(kind=FIX_MANUAL, instructions_key="connect.meta.fix.instagramInbox"),
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
