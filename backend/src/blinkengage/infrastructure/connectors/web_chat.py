"""Web Chat — a connector for the one channel with no other side.

Every other connector in this package exists to move a secret out of somebody
else's dashboard and into ours: a bot token, an app-scoped access token, an
SMTP password. Web Chat has neither a dashboard nor a secret. The widget talks
to a WebSocket this installation serves, the visitor's session token is minted
by us and lives in our Redis, and the only storage in the path is our own
object store. There is no third party to authenticate to, and therefore
nothing for the customer to paste.

That is why the capability set is two entries long, and why one of the two
means something slightly different here than it does anywhere else.

``MANUAL_CONFIGURATION`` normally reads "you may type credentials in instead
of consenting". For Web Chat it reads **there are no credentials at all**. It
is declared not because a form is wanted but because
``ConnectorProfile.connectable`` asks "is there any way to add this channel
here", and for Web Chat the answer is yes on every installation — hosted,
self-hosted, air-gapped, with provider apps configured or with none. Since
neither declared capability is one ``Connector.resolve`` gates on a platform
app, this is the only connector whose profile is identical everywhere it is
deployed. It is also the one channel in the catalog that could honestly be
connected with a single click.

``HEALTH_CHECKS`` is declared because the channel really has one, though it is
unlike anybody else's: ``WebChatProvider.health_check`` checks the attachment
store and reports ``origin="internal"``. Every other channel's red badge
raises the question "whose fault?" and this one's never does — an unhealthy
Web Chat channel is our incident, always. Worth surfacing precisely because
the alternative reading, that a first-party channel cannot fail, is wrong.
The capability is declared about the *channel*, not about ``validate`` below:
the health check exists and runs on the monitoring sweep, and the Verify step
says plainly that it has not run yet.

What is *not* declared matters as much, and each silence is load-bearing:

* No ``OAUTH``, and no ``app_key`` to configure one against — there is nobody
  to consent to. Declaring it would put an Authenticate redirect in the flow
  pointing nowhere.
* No ``AUTO_DISCOVERY`` — discovery answers "which of the things you own did
  you mean?", and a customer does not own web chat widgets the way they own
  Facebook Pages or WhatsApp numbers. There is exactly one thing to connect
  and they are already looking at it; a picker here would be a list of one,
  built from a call to nowhere.
* No ``WEBHOOKS``, ``AUTOMATIC_WEBHOOK_REGISTRATION`` or ``SHARED_WEBHOOK`` —
  inbound messages arrive on the WebSocket the visitor is holding open, not as
  a signed POST from a provider (see ``docs/architecture/web-chat.md``).
  ``WebChatProvider.verify_signature`` returns ``True`` because there is no
  signature and no signer. ``register_webhook`` is therefore left at the base
  class's refusal rather than overridden: the hook exists for connectors whose
  callback URL contains a channel id that only exists after the row is
  written, and Web Chat has no callback URL at all. Its absence here is what
  makes the base default's ``reason="not_supported"`` the literal truth.
* No ``TOKEN_REFRESH`` — nothing expires. Visitor session tokens do, on a
  sliding TTL, but they belong to a browser rather than to the channel:
  renewing one is not a repair anybody would ever be offered, and declaring
  the capability would turn "credentials expire soon" into a sentence with no
  meaning for this channel.
* No ``EMBEDDED_SIGNUP`` — there is no account, anywhere, to create.

For the same reason there is no ``repair``. A repair is offered against a
``CheckOutcome`` or a health state that names an action, and the only thing
that can be wrong with this channel is our own object store — which no button
in a customer's console fixes. Nor is there anything to re-enter: ``FIX_REENTER``
is the right fix for a mistyped credential on a pasted-secret channel, and this
one collects no value that could be mistyped.

**On the feature matrix.** What this channel carries is declared as directed
rows rather than the free strings it used to be, and three of the five rows
are one-way — which is the entire reason the free strings had to go. Every
direction below was read off ``WebChatProvider`` and the two widget frame
schemas, not off ``docs/architecture/web-chat.md``, which still describes an
edit / delete / read-receipt path the provider does not implement. Where the
code and the document disagree, the customer gets the code.

**On the empty form step.** ``credential_fields`` returns nothing, and
``steps_for`` still puts an Authenticate step in the flow, rendered as a form
with no inputs. That is the correct outcome, and the tempting fix — teaching
the wizard to skip a form when a connector describes no fields — is the wrong
one. It saves a click and costs the property this whole package exists to
protect, because the console would then be branching on a shape exactly one
channel has: a channel-specific branch wearing a capability's clothes. Nor is
the step blank from where the customer sits. It is where they name the channel,
and it is what makes connecting the second channel feel like connecting the
first. A customer who connected Telegram last week and is shown a visibly
shorter flow today reads it as something missing, not as something saved.

Nothing here makes a network call — not ``validate``, not ``diagnose``, not
``run_scenario`` — so neither ``httpx`` nor ``error_sanitizer`` appears below.
That is not an omission awaiting a later pass: with credentials permanently
empty ``redact_credentials`` would have nothing to redact, and with no
provider there is no provider error text to sanitise. Adding a timed-out
client to call nobody would be ceremony that reads, to the next person, as
evidence of a provider that does not exist. The one dependency Web Chat does
have — our own attachment store — is reached through ``WebChatProvider``,
which a connector cannot build; see ``validate`` and ``diagnose``.

**On certification, and why an almost-empty scorecard is the right one.** The
suite asks a connector to *demonstrate* behaviours against a live channel, and
Web Chat can demonstrate almost none of them from here. Not because the
channel is unfinished — it is the one connector with no unreachable path — but
because both ends of every scenario are ours and neither is reachable from a
zero-argument singleton. Sending, typing and attachments run through
``WebChatProvider``, which is built per channel with a ``channel_config_id``,
a realtime publisher and a request-scoped ``AttachmentStorage`` handle.
Inbound arrives when a visitor's browser puts a frame on a socket it is
holding open, which no certification run can cause to happen. So
``run_scenario`` answers the one row it can answer honestly — authentication,
by asking ``diagnose`` rather than by deciding it a second time — and returns
``SKIPPED`` with a specific reason for everything else.

The report that comes out is ``INCONCLUSIVE``, and that is the accurate word
rather than a gap: coverage is what *ran*, nothing ran, and the grade says so.
The failure being avoided is the opposite one. Eleven cheap passes from a
connector that never made a call would make Web Chat the best-certified
channel in the catalogue, and the first person to notice would be whoever
trusted the badge. A skip is a question left open; a fabricated pass is an
answer that is wrong.

``supported_until`` is left at the base class's ``None`` for exactly the
reason ``versions.api`` is empty: a retirement date comes from a provider's
published deprecation schedule, and there is no provider. Overriding it to
return ``None`` would restate the default and imply somebody had gone looking
for a schedule; inventing a date would be worse than either, because
administrators plan migrations around that field.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

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
    ValidationCode,
    ValidationResult,
    VerificationSpec,
)
from blinkengage.domain.connectors import Capability
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: The one line the Verify step shows. A ``warn``, not an ``ok`` — see
#: ``WebChatConnector.validate`` for why the green tick was withdrawn. Namespaced
#: like every other connector's codes (``connect.telegram.check.token``,
#: ``connect.sms.twilio.fix.buyNumber``) so the console resolves it out of the
#: same ``connect`` bundle instead of needing a rule for one channel.
_CHECK_NO_EXTERNAL_DEPENDENCY = "connect.web_chat.check.noExternalDependency"

#: What the channel is called when the customer names it nothing. A
#: translation key, deliberately, and the least bad option rather than a good
#: one: ``ChannelConfig.display_name`` is stored once and rendered verbatim
#: forever — channel list, reports, PDF and Excel exports — so whatever is
#: written here can never be translated afterwards. An English sentence would
#: be permanently English and the raw slug ``web_chat`` would be permanently
#: neither English nor Arabic, while a key at least resolves in the console
#: for a customer who never opens an export. The real fix is upstream: the
#: naming input should require a value.
_DEFAULT_DISPLAY_NAME = "connect.web_chat.defaultDisplayName"

#: The one qualification on the feature matrix. ``MEDIA`` is outbound and the
#: direction says so on its own; what the direction cannot say is that the
#: outbound frame carries a storage *key* rather than a URL, and that
#: ``WidgetMessageOut`` — the documented widget contract — does not list
#: attachments at all. A widget therefore renders an agent's file only by
#: implementing more than the published protocol currently describes, which is
#: exactly the kind of "real but qualified" support ``note_key`` exists for.
_FEATURE_MEDIA_WIDGET_SUPPORT = "connect.web_chat.feature.media.widgetSupportRequired"

#: The three diagnostic rows this connector answers, each saying *permanently
#: not applicable* rather than *not measured yet*. See ``diagnose`` for why
#: those two are worth distinguishing and why the status stays ``UNKNOWN``.
_DIAGNOSE_NO_CREDENTIAL = "connect.web_chat.diagnose.noCredentialToCheck"
_DIAGNOSE_NO_WEBHOOK = "connect.web_chat.diagnose.noWebhookToRegister"
_DIAGNOSE_NO_PROVIDER_SCOPES = "connect.web_chat.diagnose.noProviderScopes"

#: Why a scenario was not executed — one key per distinct reason rather than a
#: single shared "not applicable". A certification report is read by whoever
#: has to decide what to do next, and "we could not reach a provider" and "no
#: provider exists" and "the message has to come from a visitor's browser" are
#: three different next actions. Namespaced into this connector's own bundle
#: like its ``check`` and ``diagnose`` keys, so the console resolves them
#: without a rule for one channel.
_CERTIFY_NO_CREDENTIAL = "connect.web_chat.certify.noCredentialToAuthenticate"
_CERTIFY_NEEDS_THE_PROVIDER = "connect.web_chat.certify.needsTheProviderThisCannotBuild"
_CERTIFY_INBOUND_IS_A_VISITOR = "connect.web_chat.certify.inboundComesFromTheVisitorSocket"
_CERTIFY_NO_WEBHOOK = "connect.web_chat.certify.noWebhookToDeliverTo"
_CERTIFY_NOTHING_TO_REFRESH = "connect.web_chat.certify.nothingToRefresh"
_CERTIFY_NO_PROVIDER_SIDE_STATE = "connect.web_chat.certify.noProviderSideRegistration"
#: For a scenario kind added to the enum after this connector was written.
#: Vague on purpose: a generic reason is the honest thing to say about a
#: scenario nobody here has thought about, and it is still a skip rather than
#: an outcome that would move the score.
_CERTIFY_NOT_EXERCISABLE = "connect.web_chat.certify.notExercisableHere"

#: Every scenario the runner can hand this connector, and why each one is not
#: executed. ``AUTHENTICATION`` is absent because it is the one that is: see
#: ``run_scenario``. ``MEDIA_DOWNLOAD`` and ``READ_RECEIPT`` are absent because
#: the manifest does not claim them, so they are ``NOT_SUPPORTED`` before the
#: runner ever gets here — re-stating them would be this connector deciding
#: its own denominator.
_WHY_NOT_EXECUTED: dict[ScenarioKind, str] = {
    # Would reach a visitor's browser, and the runner only calls these when
    # somebody typed a target on purpose — so the reason returned must not be
    # "no target". It is that the publish goes through ``WebChatProvider``.
    ScenarioKind.SEND_MESSAGE: _CERTIFY_NEEDS_THE_PROVIDER,
    ScenarioKind.MEDIA_UPLOAD: _CERTIFY_NEEDS_THE_PROVIDER,
    ScenarioKind.TYPING_INDICATOR: _CERTIFY_NEEDS_THE_PROVIDER,
    ScenarioKind.RECEIVE_MESSAGE: _CERTIFY_INBOUND_IS_A_VISITOR,
    ScenarioKind.WEBHOOK_DELIVERY: _CERTIFY_NO_WEBHOOK,
    ScenarioKind.TOKEN_REFRESH: _CERTIFY_NOTHING_TO_REFRESH,
    ScenarioKind.DISCONNECT: _CERTIFY_NO_PROVIDER_SIDE_STATE,
    ScenarioKind.RECONNECT: _CERTIFY_NO_PROVIDER_SIDE_STATE,
}

#: How a diagnostic row becomes a scenario outcome. ``UNKNOWN`` maps to
#: ``SKIPPED`` and not to ``PASS``, which is the whole point of the mapping:
#: an unmeasured check is an unanswered question in both vocabularies, and the
#: two enums keep that distinction for the same reason.
_OUTCOME_OF: dict[DiagnosticStatus, Outcome] = {
    DiagnosticStatus.OK: Outcome.PASS,
    DiagnosticStatus.WARN: Outcome.WARNING,
    DiagnosticStatus.FAIL: Outcome.FAIL,
    DiagnosticStatus.UNKNOWN: Outcome.SKIPPED,
}


@ConnectorRegistry.register("web_chat")
class WebChatConnector(Connector):
    """Connecting a channel that is already here.

    Four members, none of them long, and two of them mostly explaining what
    they deliberately do not do. The module docstring above explains why it
    can be this small: there is no provider on the other end.
    """

    channel_type = "web_chat"

    #: The shortest honest manifest in the package.
    #:
    #: ``required_credentials`` is empty and that is the entire authentication
    #: story: no secret to collect means no field to describe. It is stated
    #: rather than omitted because "Web Chat asks for nothing" is a decision a
    #: reader will want to see made, and an absent declaration leaves them
    #: unable to tell a choice from an oversight.
    MANIFEST = ConnectorManifest(
        channel_type="web_chat",
        name_key="connect.web_chat.name",
        description_key="connect.web_chat.description",
        category=ConnectorCategory.EMBEDDED,
        icon="web_chat",
        capabilities=frozenset({Capability.MANUAL_CONFIGURATION, Capability.HEALTH_CHECKS}),
        # Nothing to prove: the channel is ours on both ends.
        auth_methods=(AuthMethod.NONE,),
        required_credentials=(),
        verification_steps=(
            VerificationSpec(
                key="connect.web_chat.check.noExternalDependency",
                title_key="connect.web_chat.check.noExternalDependency.title",
                codes=(ValidationCode.ADVISORY,),
            ),
        ),
        # What this channel actually carries. It used to be four free strings
        # — ``"text"``, ``"images"``, ``"documents"``, ``"typing"`` — and the
        # migration is not a rename: the strings said nothing about direction,
        # and three of the five rows below are one-way. Every line was read
        # off ``WebChatProvider`` and the widget frame schemas.
        #
        # What is absent is as deliberate, and each absence is something in
        # the provider rather than an omission here. ``edit_message`` returns
        # a ``SendResult`` and publishes nothing; ``delete_message`` and
        # ``mark_as_read`` return ``None``. Three no-ops that exist to satisfy
        # the ABC, so ``EDIT_MESSAGES``, ``DELETE_MESSAGES`` and
        # ``READ_RECEIPTS`` would each be a tick for a change the visitor
        # never sees. Nothing implements reactions, templates, broadcasts,
        # interactive messages or calls, and no widget frame carries any of
        # them.
        supported_features=(
            # Published to the visitor's Redis session channel; the gateway
            # holding that socket forwards it down. Outbound by construction
            # — a send is not a receive, and the row beneath is the other
            # half of the same sentence.
            FeatureSupport(feature=ChannelFeature.SEND_MESSAGES, direction=Direction.OUTBOUND),
            # A ``"message"`` frame off the socket, parsed by
            # ``receive_message`` into an ``InboundMessage`` and published as
            # ``message.received`` like every other channel's webhook.
            FeatureSupport(feature=ChannelFeature.RECEIVE_MESSAGES, direction=Direction.INBOUND),
            # Agent → visitor only. ``upload_attachment`` and
            # ``download_attachment`` are real work against our own object
            # store, and ``send_message`` puts the resulting refs on the
            # outbound frame — so the outbound half is not a claim, it is
            # code. The inbound half does not exist at any layer:
            # ``WidgetMessageIn`` has no attachment field and
            # ``receive_message`` parses none, so a visitor cannot send a file
            # at all. One tick against "Media" would have been wrong in
            # whichever direction the reader assumed, and the free-string list
            # above was exactly that tick, twice.
            FeatureSupport(
                feature=ChannelFeature.MEDIA,
                direction=Direction.OUTBOUND,
                note_key=_FEATURE_MEDIA_WIDGET_SUPPORT,
            ),
            # The one row that is genuinely both ways, and both ways are
            # implemented rather than assumed: ``typing_indicator`` publishes
            # to the visitor's session channel, and the gateway turns a
            # visitor's ``"typing"`` frame into ``customer_typing`` on the
            # company channel for the agent console.
            FeatureSupport(feature=ChannelFeature.TYPING_INDICATORS, direction=Direction.BOTH),
            # Inbound only — the row the free strings had no way to express.
            # A visitor's frame may carry ``reply_to_external_message_id``,
            # and the ingest consumer resolves it to a ``Message`` row the
            # console renders as a quote. The return path is empty and not by
            # oversight: ``ConversationService.send_reply`` sets a reply
            # reference only for providers declaring
            # ``supports_invisible_reply_threading``, which ``WebChatProvider``
            # leaves at ``False``. So nothing ever populates the field
            # ``send_message`` would happily forward, and claiming ``BOTH``
            # here would promise the customer a quoted reply we never send.
            FeatureSupport(feature=ChannelFeature.THREADING, direction=Direction.INBOUND),
        ),
        # Beta, and the reasoning matters because this is the one connector in
        # the package with no unreachable path: no OAuth that cannot run, no
        # discovery that returns nothing, no webhook registration that refuses,
        # no repair that cannot repair. Everything it declares, it does, on
        # every installation. What keeps it off ``PRODUCTION`` is not a hole in
        # the code but the promise that badge makes — "supported, and changes
        # to it are backwards-compatible". Nothing here has carried a
        # customer's conversation yet, and the contract this channel depends on
        # is still moving: the widget frame protocol grew its ``type``
        # discriminator in July, and ``WidgetMessageOut`` still does not
        # describe the attachments ``send_message`` already sends. Promising
        # backwards compatibility across that would be promising something we
        # would break. ``BETA`` — feature-complete and being proven — is what
        # is true today.
        maturity=Maturity.BETA,
        # ``api`` is empty, and this is the only connector in the package
        # where empty is the honest value rather than a gap. The field names
        # *the provider's* API version, and Web Chat has no provider. The
        # widget protocol is not a substitute: no frame carries a version,
        # nothing is negotiated, and ``WidgetMessageIn`` accommodates an older
        # client by defaulting a missing field rather than by branching on a
        # number. Writing one here would put a version on the channel detail
        # screen that neither side ever agreed to.
        versions=VersionInfo(connector="1.0.0", api="", minimum_platform="1.0.0"),
    )

    @property
    def manifest(self) -> ConnectorManifest:
        return self.MANIFEST

    # --- Verify -------------------------------------------------------

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        """One line, and — of the two options — the downgraded one.

        **Downgraded, not probed.** The choice was between reaching the
        attachment store through ``WebChatProvider.health_check`` and telling
        the customer plainly that nothing was reached, and only the second is
        available from here. That provider is constructed per channel with a
        ``channel_config_id``, a ``company_id``, a realtime publisher and an
        ``AttachmentStorage`` handle; the store itself is request-scoped
        dependency-injected wiring (``api.deps.get_attachment_store``). A
        connector is a zero-argument singleton the registry builds at import
        time, and ``Attempt`` carries deployment facts rather than
        infrastructure handles — deliberately, since a connector that could
        reach into the container would be a connector that could reach past
        this contract. There is no honest way to construct the provider here,
        so the probe does not happen.

        What the check must therefore not do is what it used to: return
        ``ok``. The Verify step is where a customer is told what was tested,
        and a green tick that tested nothing is worse than a missing line —
        it is the checklist lying in the direction customers trust. So the
        one outcome is a ``warn`` whose code says exactly what holds: there is
        no external dependency to verify, and the one internal dependency has
        not been touched yet. ``warn`` never blocks (``blocks_connection``),
        which is right — nothing is wrong, something is merely unverified.

        No ``fix``, because there is nothing for the customer to press. The
        attachment store is ours; if it is down, that is an incident and
        ``channel_health_check_task`` raises it on the next sweep with
        ``origin="internal"``, against the channel that by then exists.

        ``attempt`` is unused and stays in the signature: it is the contract's
        shape, and a connector that later grows a real probe should not also
        have to change how it is called.
        """
        return (
            ValidationResult(
                ValidationCode.ADVISORY,
                channel_type=self.channel_type,
                params={"check": _CHECK_NO_EXTERNAL_DEPENDENCY},
            ),
        )

    # --- Diagnose -----------------------------------------------------

    async def diagnose(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> DiagnosticReport:
        """Three rows that will never have an answer, and nothing else.

        The connector's half of a diagnostic report is the half only it can
        produce by *asking the provider*: does the token still work, is the
        webhook registered over there, which scopes were actually granted,
        how much throttle headroom is left. Web Chat has no provider, so
        there is nobody to ask and nothing this method could measure. The
        interesting question is therefore not what to report but whether to
        report anything at all.

        **Not ``OK``, on any row.** A green tick on Authentication would say
        "the stored credential still works" about a channel that stores no
        credential. It would be true in the sense of never failing and false
        in the sense a support engineer reads it, and a panel that invents
        one verified line is worse than a panel with none — the whole reason
        anybody trusts this screen is that ``UNKNOWN`` was kept as a separate
        value from ``OK``.

        **Not silence either.** ``complete()`` fills every unanswered key
        with a bare ``UNKNOWN``, which reads as "nobody has got round to
        checking" — so a support engineer with a customer on the phone spends
        their next minute looking for a token check that will never exist for
        this channel. Saying ``UNKNOWN`` *with a reason* costs nothing and
        closes that question: not unmeasured, unmeasurable, permanently, by
        design. That is the one thing this connector genuinely knows, and it
        knows it from the manifest rather than from a network call —
        ``required_credentials`` is empty, ``required_permissions`` is empty,
        and no webhook capability is declared because inbound arrives on the
        visitor's own socket.

        **Only three rows, because the connector wins the merge.**
        ``merge()`` takes the connector's entry over the platform's for the
        same key, on the reasoning that a real measurement beats a remembered
        one. Here it would be the reverse: an ``UNKNOWN`` from this method
        would *suppress* whatever the platform inferred from stored state. So
        the platform's own half — last successful sync, last failed request,
        response times, retry queue, overall health — is left strictly alone,
        and two of the connector-side keys are left alone as well:

        * ``RATE_LIMITS``, because "not applicable" would be the wrong
          lesson. There is no *provider* throttle, but the visitor session
          endpoint is rate limited by us (``webchat_session``, 30 a minute),
          and that limiter is both real and invisible from here. Telling a
          support engineer to stop looking at throttling would point them
          away from the only throttle that can actually bite this channel.
        * ``API_VERSION``, because the manifest already carries
          ``versions.api`` and the platform holds the manifest. Answering
          here would displace that with nothing better.

        **The one thing worth probing, this cannot reach.** Web Chat's single
        dependency is our own attachment store, and ``WebChatProvider``
        checks it — but a provider is built per channel with a
        ``channel_config_id``, a realtime publisher and a request-scoped
        ``AttachmentStorage`` handle, while a connector is the zero-argument
        singleton the registry builds at import time. ``validate`` documents
        the same wall for the same reason. That check belongs to the
        monitoring sweep, which already runs it and already reports
        ``origin="internal"`` when it fails.

        Cannot raise: this builds a tuple of module constants and performs no
        I/O, no parsing and no provider call. ``credentials`` is empty for
        every Web Chat channel ever connected and ``context`` describes an
        installation this method does not consult; both stay in the
        signature because they are the contract's shape, and a connector that
        later grows a real probe should not also have to change how it is
        called.
        """
        return DiagnosticReport(
            channel_type=self.channel_type,
            items=(
                Diagnostic(
                    key=DiagnosticKey.AUTHENTICATION,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAGNOSE_NO_CREDENTIAL,
                ),
                Diagnostic(
                    key=DiagnosticKey.WEBHOOK_STATUS,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAGNOSE_NO_WEBHOOK,
                ),
                Diagnostic(
                    key=DiagnosticKey.PERMISSIONS,
                    status=DiagnosticStatus.UNKNOWN,
                    detail_key=_DIAGNOSE_NO_PROVIDER_SCOPES,
                ),
            ),
        )

    # --- Connect ------------------------------------------------------

    async def connect(self, *, company_id: UUID, attempt: Attempt) -> tuple[Connection, ...]:
        """Nothing to call, and one row to write.

        The credentials dict is empty on purpose and stays empty:
        ``WebChatProvider`` reads none, ``WebChatCredentials`` validates an
        empty object, and anything else the attempt happened to carry would be
        encrypted, backed up, and never read again. ``attempt.inputs`` and
        ``attempt.grant`` are both ignored rather than merged — the form has no
        fields and there was no consent, so anything present in either is
        something nobody asked for. Storing a secret nothing consumes is how a
        credential outlives the reason it was collected.

        ``external_id`` is ``None`` because there is no provider-side identity
        to record. The ``external_thread_id`` this channel routes on is a
        visitor's session token, minted per browser at runtime; nothing sits
        above it at channel level, and inventing an id here would imply a
        routing key nothing sets. ``webhook_secret`` is ``None`` for the same
        reason it would be unused: no third party posts here, so there is no
        delivery for a secret to verify.

        The display name is the customer's own, read from
        ``Attempt.display_name`` — a first-class field on the attempt rather
        than a value fished out of credentials, which is where it used to be
        looked for and where, for this connector, it could never be. Other
        connectors fall back to a provider-side name (a bot's username, a
        phone number, a page title); this one has none, so it falls back to a
        translation key. See ``_DEFAULT_DISPLAY_NAME`` for why a key and not
        the slug.
        """
        return (
            Connection(
                channel_type=self.channel_type,
                display_name=attempt.display_name.strip() or _DEFAULT_DISPLAY_NAME,
                credentials={},
            ),
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
        """One row it can answer, and eight it says it cannot.

        Every judgement that would let this connector flatter itself has
        already been made by the runner: what the manifest never claimed is
        ``NOT_SUPPORTED`` before this is called (``MEDIA_DOWNLOAD``, because
        ``MEDIA`` is declared ``OUTBOUND``; ``READ_RECEIPT``, because
        ``mark_as_read`` is a no-op and the row was left off), and anything
        that would emit or mutate has already been gated. So what arrives here
        is a scenario somebody meant to run, and the only question left is
        whether it can be run — which is the one question a connector is
        allowed to answer about itself, and only by trying.

        **Authentication, by asking ``diagnose``.** The scenario and the
        diagnostic row are the same question, so they are the same call: two
        implementations would eventually disagree, and the screen showing a
        green tick beside a certification skip would be the one nobody could
        explain. The mapping is deliberate in one place — ``UNKNOWN`` becomes
        ``SKIPPED``, never ``PASS`` — and that is what makes it safe to reuse a
        method that today measures nothing. Web Chat's ``diagnose`` reports
        ``UNKNOWN`` with a reason ("there is no credential to check"), so the
        scenario skips with a reason, and the report says nobody proved
        anything rather than claiming somebody did. If this channel ever grows
        something to authenticate against, ``diagnose`` grows the probe and
        this row starts passing on its own — which is the point of routing
        through it rather than around it.

        **The other eight, and why a skip is the honest answer to each.**
        Send, typing and media upload arrive only when an operator typed a
        target, so the reason returned is never "no target" — it is that the
        act of publishing goes through ``WebChatProvider``, built per channel
        with a ``channel_config_id``, a realtime publisher and a request-scoped
        ``AttachmentStorage`` handle that a singleton built at import time
        cannot obtain. Receive is not gated at all and still cannot run: an
        inbound message exists when a visitor's browser puts a frame on the
        socket it is holding, and a certification run cannot make a visitor
        type. Webhook delivery has no webhook — inbound is that socket, and
        ``verify_signature`` returns ``True`` because there is no signer. Token
        refresh has no token: visitor sessions expire in Redis and belong to a
        browser, not to the channel. Disconnect and reconnect, elsewhere, mean
        deregistering and re-registering with a provider; here nothing was ever
        registered anywhere, and the row's own lifecycle belongs to
        ``ChannelConfigService`` rather than to this contract.

        **Two things that were tempting, and are not done.** The first is
        exercising ``WebChatProvider.receive_message`` on a synthetic frame:
        it is pure parsing and would pass. It would also be a unit test wearing
        a certification's clothes — the suite's promise is that a *live channel*
        was made to work, and a parser returning an ``InboundMessage`` says
        nothing about whether a visitor's socket is up, whether Redis is
        reachable, or whether the gateway is forwarding. The second is building
        an ``AttachmentStore`` from settings to prove ``MEDIA_UPLOAD``: that
        would be a connector reaching into the container, which is precisely
        what ``Attempt`` carrying deployment facts instead of infrastructure
        handles exists to prevent — and it would leave a real object in the
        real bucket under a channel id this method would have had to invent.
        Both were rejected for the same reason: a pass has to mean the thing
        the report says it means.

        Cannot raise. The only call is to this class's own ``diagnose``, which
        builds a tuple of module constants and performs no I/O, no parsing and
        no provider call; everything else here is a dict lookup and a frozen
        dataclass. ``target`` is unread for the same reason ``credentials`` is
        empty, and both stay in the signature because they are the contract's
        shape. ``duration_ms`` is left at zero rather than measured: the runner
        times every scenario itself, on the reasoning that a connector
        reporting its own duration is a connector reporting its own
        performance.
        """
        if kind is ScenarioKind.AUTHENTICATION:
            return await self._authentication(credentials=credentials, context=context)
        return ScenarioResult(
            kind=kind,
            outcome=Outcome.SKIPPED,
            detail_key=_WHY_NOT_EXECUTED.get(kind, _CERTIFY_NOT_EXERCISABLE),
        )

    async def _authentication(
        self, *, credentials: dict[str, Any], context: DeploymentContext
    ) -> ScenarioResult:
        """The authentication scenario, read off the diagnostic it duplicates.

        The status is carried into ``diagnostics`` as evidence rather than as
        copy, so a reader of the report can see *which* row this outcome came
        from without having to run the diagnostics panel and compare by eye.
        """
        report = await self.diagnose(credentials=credentials, context=context)
        row = next(
            (item for item in report.items if item.key is DiagnosticKey.AUTHENTICATION),
            None,
        )
        if row is None:
            return ScenarioResult(
                kind=ScenarioKind.AUTHENTICATION,
                outcome=Outcome.SKIPPED,
                detail_key=_CERTIFY_NO_CREDENTIAL,
            )

        evidence = {"source": "diagnose", "diagnostic_status": row.status.value}
        if row.detail_key:
            evidence["diagnostic_detail_key"] = row.detail_key
        unmeasured = row.status is DiagnosticStatus.UNKNOWN
        return ScenarioResult(
            kind=ScenarioKind.AUTHENTICATION,
            outcome=_OUTCOME_OF[row.status],
            detail_key=_CERTIFY_NO_CREDENTIAL if unmeasured else row.detail_key,
            diagnostics=evidence,
        )


__all__ = ["WebChatConnector"]
