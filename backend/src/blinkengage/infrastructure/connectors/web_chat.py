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
The capability is declared about the *channel*, not about ``check`` below:
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

Nothing here makes a network call, so neither ``httpx`` nor
``error_sanitizer`` appears below. That is not an omission awaiting a later
pass: with credentials permanently empty ``redact_credentials`` would have
nothing to redact, and with no provider there is no provider error text to
sanitise. The one dependency Web Chat does have — our own attachment store —
is reached through ``WebChatProvider``, which a connector cannot build; see
``check``.
"""

from __future__ import annotations

from uuid import UUID

from blinkengage.domain.connector import (
    Attempt,
    Connection,
    Connector,
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
#: ``WebChatConnector.check`` for why the green tick was withdrawn. Namespaced
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


@ConnectorRegistry.register("web_chat")
class WebChatConnector(Connector):
    """Connecting a channel that is already here.

    Three members, none of them long. The module docstring above explains why
    it can be this small: there is no provider on the other end.
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
        capabilities=frozenset(
            {Capability.MANUAL_CONFIGURATION, Capability.HEALTH_CHECKS}
        ),
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
        supported_features=("text", "images", "documents", "typing"),
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


__all__ = ["WebChatConnector"]
