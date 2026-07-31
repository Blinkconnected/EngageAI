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

Everything customer-visible below is a translation key, and every string
that starts life inside an exception goes through ``error_sanitizer`` first:
this provider carries its bot token in the request URL, so an unsanitised
``httpx`` error message is a live credential written into whatever storage
the caller happens to keep failures in.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

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


async def _call(
    client: httpx.AsyncClient,
    *,
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """One Bot API call, as ``(status, body)``.

    The single place in this module where the token is interpolated into a
    URL, and the reason nothing here calls ``raise_for_status``: the
    exception it raises embeds the request URL, token and all. The status
    code is returned instead so callers can tell Telegram rejecting a
    credential (4xx, and 200 with ``ok: false``) from Telegram being
    unwell (5xx) without ever touching an ``httpx`` error string.
    """
    url = f"{_API_BASE_URL}/bot{token}/{method}"
    response = await client.get(url) if payload is None else await client.post(url, json=payload)
    try:
        body = response.json()
    except ValueError:
        # A proxy or captive portal answering with HTML. Indistinguishable
        # from a provider outage from here, and handled as one.
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


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
        supported_features=("text", "images", "documents", "edit", "delete", "typing"),
        documentation=(
            DocumentationLink(key="connect.telegram.docs.botFather", url="https://core.telegram.org/bots#botfather"),
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
