"""The five real connectors, against the contract the fictional ones prove.

``tests/unit/test_connectors.py`` deliberately knows nothing about WhatsApp:
its connectors are invented, because the property under test there is that the
flow falls out of capabilities and never out of a channel name. This file is
the other half, and it is allowed to know what a Page is. What it tests is
whether the five modules in ``infrastructure/connectors`` — seven registered
channel types, since Meta is one family of three — actually keep the promises
the contract lets them make, because a connector can satisfy every type in
``domain/connector.py`` and still hand back a credentials dict the transport
provider cannot send with.

That is the failure this suite exists to catch, and it is worth naming
precisely. ``Connector.connect`` returns a ``Connection``; something else
writes the row; ``ChannelProvider`` reads it back weeks later on the first
outbound message. Nothing in between compares the two. A connector that stores
``page`` where the provider reads ``page_id`` produces a channel that saves
cleanly, reports itself healthy, shows green in the console — and silently
fails to deliver. There is no symptom to diagnose and no error to grep for, so
the only place the mismatch can be caught is here, one assertion away from
both halves.

Everything that would touch a network is mocked with ``httpx.MockTransport``
(the pattern every provider test in this suite already uses — there is no
respx). An autouse fixture points every client this package builds at a
transport that refuses, so a connector that grows a new call and forgets to
mock it fails loudly rather than reaching out of the test process.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import orjson
import pytest

import blinkengage.infrastructure.connectors as connectors_package
from blinkengage.domain.connector import (
    Attempt,
    Connector,
    DeploymentContext,
    Resource,
)
from blinkengage.domain.connectors import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    FIX_ACTION,
    FIX_MANUAL,
    FIX_REAUTHORIZE,
    FIX_REENTER,
    Capability,
    CheckOutcome,
    StepId,
    StepKind,
    steps_for,
)
from blinkengage.infrastructure.channels.credential_schemas import (
    _CREDENTIAL_SCHEMAS,
    validate_channel_credentials,
)
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.connectors import ConnectorRegistry
from blinkengage.infrastructure.connectors.meta import META_APP

# Importing the provider package is what populates ``ChannelRegistry`` — the
# connector half of each channel is worthless if the transport half is missing,
# and one of the tests below checks that the two registries agree.
import blinkengage.infrastructure.channels.providers  # noqa: E402, F401  isort:skip

HOSTED = DeploymentContext(
    public_base_url="https://engage.example.com", configured_apps=frozenset({META_APP})
)
BARE = DeploymentContext(public_base_url="https://engage.example.com")

#: Every key a ``ChannelProvider`` (or, for email, the IMAP poll task) actually
#: dereferences out of the stored credentials dict. Read off the providers
#: themselves — ``providers/whatsapp.py``, ``providers/_meta_messaging.py``,
#: ``providers/telegram.py``, ``providers/email.py``, ``gateways/twilio.py`` —
#: and the reason this table is hand-written rather than derived: deriving it
#: from the connectors would make the comparison tautological, and deriving it
#: from the pydantic schemas would miss the keys no schema knows about. It is
#: the second opinion, so it has to come from the other side.
PROVIDER_CREDENTIAL_KEYS: dict[str, frozenset[str]] = {
    "whatsapp": frozenset(
        {"phone_number_id", "access_token", "verify_token", "graph_api_base_url", "api_version"}
    ),
    "messenger": frozenset(
        {"page_id", "access_token", "verify_token", "graph_api_base_url", "api_version"}
    ),
    "instagram": frozenset(
        {"instagram_id", "access_token", "verify_token", "graph_api_base_url", "api_version"}
    ),
    "telegram": frozenset({"bot_token", "api_base_url", "file_base_url"}),
    "email": frozenset(
        {
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_use_tls",
            "from_address",
            "default_subject",
            "imap_host",
            "imap_port",
            "imap_username",
            "imap_password",
            "imap_use_ssl",
            "imap_folder",
        }
    ),
    "sms": frozenset({"gateway", "account_sid", "auth_token", "from_number"}),
    # Web Chat's provider reads nothing: the visitor's session lives in Redis
    # and the transport is our own WebSocket.
    "web_chat": frozenset(),
}

#: The subset without which the first outbound message cannot be composed at
#: all — the provider dereferences these with no usable default.
KEYS_REQUIRED_TO_SEND: dict[str, frozenset[str]] = {
    "whatsapp": frozenset({"phone_number_id", "access_token"}),
    "messenger": frozenset({"page_id", "access_token"}),
    "instagram": frozenset({"instagram_id", "access_token"}),
    "telegram": frozenset({"bot_token"}),
    "email": frozenset({"smtp_host"}),
    "sms": frozenset({"gateway", "account_sid", "auth_token", "from_number"}),
    "web_chat": frozenset(),
}

_RealAsyncClient = httpx.AsyncClient

#: A code the console can translate: no whitespace, no sentence punctuation,
#: not capitalised. Deliberately permissive about *shape* — the package uses
#: both dotted keys (``connect.telegram.check.token``) and bare snake_case
#: codes (``platform_app_not_configured``, ``not_supported``), and the contract
#: asks only that neither is prose. Anything with a space in it is a string
#: that can only ever be English, which is the whole failure being prevented.
_KEY_PATTERN = re.compile(r"^[a-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")


def looks_like_key(value: str) -> bool:
    return bool(_KEY_PATTERN.fullmatch(value))


class Recorder:
    """Every request a connector made, and how each client was constructed.

    The constructor kwargs are recorded because "did this call have a timeout"
    is not answerable from the request — a client built without one hangs on a
    black-holed connection for as long as the kernel allows, which on the
    Verify step is a customer watching a spinner until they give up.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.client_kwargs: list[dict[str, Any]] = []

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def route(monkeypatch: pytest.MonkeyPatch, handler: Any) -> Recorder:
    """Point every ``httpx.AsyncClient`` in the process at ``handler``.

    Patched on the ``httpx`` module rather than per connector module: all five
    connectors do ``import httpx`` and call ``httpx.AsyncClient(...)``, so one
    patch covers a connector added tomorrow as well.
    """
    recorder = Recorder()

    def record_and_handle(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        recorder.client_kwargs.append(dict(kwargs))
        mocked = {**kwargs, "transport": httpx.MockTransport(record_and_handle)}
        return _RealAsyncClient(*args, **mocked)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return recorder


@pytest.fixture(autouse=True)
def refuse_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file may reach the internet.

    Not defensive tidiness: a connector that grows a second Graph hop and is
    not mocked for it would otherwise pass here and fail in CI, or worse, pass
    everywhere and quietly call Meta from a developer's laptop.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unmocked network call to {request.url}")

    route(monkeypatch, refuse)


def fake_smtp(
    monkeypatch: pytest.MonkeyPatch, *, connect_error: bool = False, login_error: bool = False
) -> list[dict[str, Any]]:
    """Stand in for ``aiosmtplib.SMTP`` — email's only outbound dependency.

    Returns the constructor kwargs of every connection opened, for the same
    reason ``Recorder`` keeps the httpx ones.
    """
    opened: list[dict[str, Any]] = []

    class _FakeSMTP:
        def __init__(self, **kwargs: Any) -> None:
            opened.append(kwargs)

        async def __aenter__(self) -> _FakeSMTP:
            if connect_error:
                raise OSError("Connection refused")
            return self

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

        async def noop(self) -> None:
            return None

        async def login(self, username: str, password: str) -> None:
            if login_error:
                raise RuntimeError("535 Authentication credentials invalid")

    monkeypatch.setattr("blinkengage.infrastructure.connectors.email.aiosmtplib.SMTP", _FakeSMTP)
    return opened


def overrides(connector: Connector, member: str) -> bool:
    """Whether this connector implements ``member`` itself.

    Compared against ``Connector``'s own function object rather than checked
    with ``hasattr``: every connector *has* every member, since the base class
    supplies a refusal for each. What matters is whether it was replaced.
    """
    return getattr(type(connector), member) is not getattr(Connector, member)


def filled_form(connector: Connector) -> dict[str, Any]:
    """A plausible submission of whatever form this connector describes.

    Derived from ``credential_fields()`` so a connector that grows a field is
    exercised through it without this file being edited.
    """
    values: dict[str, Any] = {}
    for field in connector.credential_fields():
        if field.kind == "select":
            values[field.name] = field.options[0][0]
        elif field.kind == "number":
            values[field.name] = "587"
        elif field.kind == "boolean":
            values[field.name] = True
        else:
            values[field.name] = f"{field.name}-value"
    return values


def json_response(
    request: httpx.Request, body: dict[str, Any], status: int = 200
) -> httpx.Response:
    return httpx.Response(status, json=body)


class TestConnectHandsBackWhatTheProviderReads:
    """The reason this file exists.

    Each test connects a channel the way the wizard would and then asks the
    two questions nothing else in the codebase asks: does this dict pass the
    schema the channel service will validate it against, and is every key in
    it one the provider will actually look up. Fail either and the channel
    connects, goes green, and never sends.
    """

    def assert_storable(self, channel_type: str, credentials: dict[str, Any]) -> None:
        # Raises ``InvalidChannelCredentialsError`` if the shape is wrong, so
        # this is the same gate ``ChannelConfigService.create`` applies.
        validate_channel_credentials(channel_type, credentials)

        reads = PROVIDER_CREDENTIAL_KEYS[channel_type]
        stored = set(credentials)
        assert stored <= reads, (
            f"{channel_type} stores {stored - reads}, which its provider never reads: "
            "an encrypted value kept forever and consulted never"
        )
        assert KEYS_REQUIRED_TO_SEND[channel_type] <= stored, (
            f"{channel_type} is missing {KEYS_REQUIRED_TO_SEND[channel_type] - stored} — "
            "the channel would save cleanly and fail on its first outbound message"
        )

    async def test_telegram_stores_the_token_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/bot123456:AA/getMe"
            return json_response(
                request,
                {"ok": True, "result": {"id": 42, "username": "acme_bot", "first_name": "Acme"}},
            )

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(context=BARE, inputs={"bot_token": " 123456:AA "}),
        )

        self.assert_storable("telegram", connection.credentials)
        # Trimmed on the way in: a token pasted with a trailing newline is the
        # difference between a request and an ``httpx.InvalidURL``.
        assert connection.credentials == {"bot_token": "123456:AA"}
        assert connection.external_id == "42"

    async def test_email_stores_the_form_and_drops_the_rest(self) -> None:
        connector = ConnectorRegistry.get("email")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=BARE,
                inputs={
                    "smtp_host": "smtp.example.com",
                    "smtp_port": "587",
                    "smtp_username": "support@example.com",
                    "smtp_password": "hunter2",
                    "smtp_use_tls": False,
                    "from_address": "support@example.com",
                    "imap_host": "",
                    # Neither of these was asked for. Anything that reaches
                    # this dict is encrypted and kept forever, so the set of
                    # things it can hold is the set of things the form drew.
                    "display_name": "typed into the wrong box",
                    "smtp_secret_backdoor": "x",
                },
            ),
        )

        self.assert_storable("email", connection.credentials)
        assert "display_name" not in connection.credentials
        assert "smtp_secret_backdoor" not in connection.credentials
        # A blank is dropped rather than stored: the provider reads its
        # defaults with ``get(name, default)`` and ``int("")`` raises where a
        # missing port would quietly have become 587.
        assert "imap_host" not in connection.credentials

    async def test_web_chat_stores_nothing_at_all(self) -> None:
        connector = ConnectorRegistry.get("web_chat")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            # Both dicts carry values nobody asked for — the form has no
            # fields and there was no consent, so both must be ignored rather
            # than merged. A credential stored here outlives the reason it was
            # collected, and nothing will ever read it back.
            attempt=Attempt(
                context=BARE, inputs={"anything": "at all"}, grant={"access_token": "leak"}
            ),
        )

        self.assert_storable("web_chat", connection.credentials)
        assert connection.credentials == {}
        assert connection.webhook_secret is None

    async def test_sms_stores_the_carrier_and_its_own_keys(self) -> None:
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=BARE,
                inputs={
                    "gateway": "twilio",
                    "account_sid": "AC123",
                    "auth_token": "secret",
                    "from_number": " +15551234567 ",
                    # A Vonage field on a Twilio submission: the union form
                    # shows every carrier's inputs, so this is what an honest
                    # form actually posts and it must not be stored.
                    "api_key": "vonage-only",
                },
            ),
        )

        # SMS has no entry in ``_CREDENTIAL_SCHEMAS`` — Phase 1 covered four
        # channels and this is not one of them — so ``validate`` passes
        # anything. The provider-key half of this assertion is doing all of
        # the work here, which is exactly why it is not derived from a schema.
        self.assert_storable("sms", connection.credentials)
        assert connection.credentials == {
            "gateway": "twilio",
            "account_sid": "AC123",
            "auth_token": "secret",
            "from_number": "+15551234567",
        }
        assert connection.external_id == "+15551234567"
        assert connection.external_parent_id == "AC123"
        # Twilio signs deliveries with the auth token that is already stored.
        # A random secret here would be a column nothing verifies against —
        # green channel, every inbound message silently discarded.
        assert connection.webhook_secret is None

    @pytest.mark.parametrize(
        ("channel_type", "resource_key", "subscribe_on"),
        [
            # WhatsApp subscribes on the business account the number hangs
            # off, Instagram on the Page it is reached through, Messenger on
            # the Page itself. Three different nodes, one code path.
            ("whatsapp", "phone_number_id", "WABA1"),
            ("messenger", "page_id", "PAGE1"),
            ("instagram", "instagram_id", "PAGE1"),
        ],
    )
    async def test_meta_after_consent_stores_the_resource_and_its_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
        channel_type: str,
        resource_key: str,
        subscribe_on: str,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith(f"/{subscribe_on}/subscribed_apps")
            return json_response(request, {"success": True})

        recorder = route(monkeypatch, handler)
        connector = ConnectorRegistry.get(channel_type)
        assert connector is not None

        resource = Resource(
            id="RESOURCE1",
            label="Acme Support",
            context={
                # The Page token, not the user token. Narrower and more
                # durable, and the reason a leaked channel row cannot act on
                # everything the customer approved.
                "access_token": "PAGE-TOKEN",
                "parent_id": subscribe_on,
                "subscribe_on": subscribe_on,
            },
        )
        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=HOSTED, grant={"access_token": "USER-TOKEN"}, selection=(resource,)
            ),
        )

        self.assert_storable(channel_type, connection.credentials)
        assert connection.credentials == {resource_key: "RESOURCE1", "access_token": "PAGE-TOKEN"}
        assert connection.external_id == "RESOURCE1"
        assert connection.external_parent_id == subscribe_on
        # The installation's App Secret verifies inbound events, so there is
        # nothing per channel to store — one plaintext copy of the
        # highest-value secret we hold, per channel, forever, is the
        # alternative.
        assert connection.webhook_secret is None
        assert len(recorder.requests) == 1

    async def test_meta_by_hand_keeps_the_app_secret_out_of_the_credentials(self) -> None:
        """The one value on this path that belongs in a column, not the blob.

        A secret written to both places has two sources of truth and only one
        of them is ever read, which is how a rotated App Secret goes on
        verifying for weeks in one place and failing in the other.
        """
        connector = ConnectorRegistry.get("messenger")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=BARE,
                inputs={
                    "page_id": "PAGE1",
                    "access_token": "PAGE-TOKEN",
                    "webhook_secret": "app-secret",
                },
            ),
        )

        self.assert_storable("messenger", connection.credentials)
        assert "webhook_secret" not in connection.credentials
        assert connection.webhook_secret == "app-secret"

    async def test_meta_supplies_the_recipient_key_its_schema_does_not_require(self) -> None:
        """``MetaMessagingCredentials`` would not have caught its absence.

        The schema names ``access_token`` and nothing that identifies *which*
        Page or Instagram account — but ``MetaMessagingProvider`` reads
        ``page_id``/``instagram_id`` on every send. So for these two channels
        the schema cannot be the thing that guarantees a sendable dict, and
        this assertion is the only one standing between a hand-connected
        Messenger channel and a silent delivery failure.
        """
        for channel_type, key in (("messenger", "page_id"), ("instagram", "instagram_id")):
            connector = ConnectorRegistry.get(channel_type)
            assert connector is not None
            (connection,) = await connector.connect(
                company_id=uuid4(),
                attempt=Attempt(
                    context=BARE, inputs={key: "RESOURCE1", "access_token": "PAGE-TOKEN"}
                ),
            )
            # Passes with the key missing, which is the point being made.
            validate_channel_credentials(channel_type, {"access_token": "x"})
            assert connection.credentials[key] == "RESOURCE1"

    def test_the_provider_key_table_covers_every_registered_connector(self) -> None:
        """A new connector cannot slip past the assertion above.

        If it is registered and has no entry here, every test in this class
        raises ``KeyError`` on it rather than quietly skipping it.
        """
        registered = {connector.channel_type for connector in ConnectorRegistry.all()}

        assert registered == set(PROVIDER_CREDENTIAL_KEYS)
        assert registered == set(KEYS_REQUIRED_TO_SEND)
        # And a connector with no transport behind it is a channel a customer
        # can connect and then cannot use.
        assert registered <= ChannelRegistry.known_channel_types()

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_every_form_field_is_a_key_the_provider_reads(self, connector: Connector) -> None:
        """A field the provider never reads is a question with no purpose.

        Derived from ``credential_fields()`` rather than listed, so a
        connector that adds an input the transport layer knows nothing about
        fails here — the same mismatch as a wrong key, caught one step
        earlier, at the moment the customer is asked to type it.
        """
        asked_for = {field.name for field in connector.credential_fields()}

        assert asked_for <= PROVIDER_CREDENTIAL_KEYS[connector.channel_type]

    @pytest.mark.parametrize(
        "channel_type", sorted(set(_CREDENTIAL_SCHEMAS) & set(PROVIDER_CREDENTIAL_KEYS))
    )
    def test_no_schema_describes_a_key_nothing_reads(self, channel_type: str) -> None:
        """The third side of the same triangle: schema, connector, provider.

        A schema field the provider ignores is a value the console will
        happily accept, encrypt and store, and that nothing will ever consult
        — indistinguishable from a working setting to whoever typed it.
        """
        schema = _CREDENTIAL_SCHEMAS[channel_type]

        assert set(schema.model_fields) <= PROVIDER_CREDENTIAL_KEYS[channel_type]


class TestDeclaredCapabilitiesAreTrue:
    """A capability is a promise the flow is derived from.

    ``steps_for`` renders a redirect for ``OAUTH`` and a picker for
    ``AUTO_DISCOVERY``, and the console never asks which channel it is looking
    at. So a declaration that is not backed by an implementation is not an
    unused method — it is a screen with nothing behind it, and the customer
    meets it at the one moment they have committed to connecting.

    Every test here is parametrised over the registry, so a connector added
    next quarter is covered without this file being touched.
    """

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_automatic_webhook_registration_is_backed_by_the_hook(
        self, connector: Connector
    ) -> None:
        """With one carve-out, and the carve-out is the interesting part.

        ``register_webhook`` exists because a per-channel callback URL
        contains the channel's id, which is assigned after ``connect``
        returns. A ``SHARED_WEBHOOK`` connector has no per-channel URL at all
        — Meta's callback is configured once on the app — so it automates the
        equivalent inside ``connect`` (``subscribed_apps``) and must *not*
        implement the hook. The two are told apart only by the co-declared
        capability, which is a gap in the contract worth remembering here.
        """
        declares_automation = Capability.AUTOMATIC_WEBHOOK_REGISTRATION in connector.declares
        shared = Capability.SHARED_WEBHOOK in connector.declares

        if declares_automation and not shared:
            assert overrides(connector, "register_webhook"), (
                f"{connector.channel_type} promises automatic webhook registration and "
                "inherits the base class's refusal — the customer is told nothing is "
                "left to do and inbound never arrives"
            )
        if shared:
            assert not overrides(connector, "register_webhook")

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_the_hook_is_only_implemented_where_it_is_declared(self, connector: Connector) -> None:
        """The converse, which matters just as much: a connector that quietly
        registers webhooks without declaring it leaves the checklist telling
        the customer to go and paste a URL somebody already pasted."""
        if overrides(connector, "register_webhook"):
            assert Capability.AUTOMATIC_WEBHOOK_REGISTRATION in connector.declares

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_auto_discovery_is_backed_by_discover(self, connector: Connector) -> None:
        """Declaring it puts a ``RESOURCE_PICKER`` step in the flow. The base
        ``discover`` returns ``()``, so an undeclared implementation is a
        picker with nothing in it — which reads to a customer as "we cannot
        see your Pages", the single most alarming thing this flow can say."""
        declared = Capability.AUTO_DISCOVERY in connector.declares

        assert declared is overrides(connector, "discover")

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_oauth_is_backed_by_an_authorize_url_and_an_app_to_ask(
        self, connector: Connector
    ) -> None:
        """``OAUTH`` puts an ``OAUTH_REDIRECT`` step in front of the customer.
        The base ``authorize_url`` raises, so an undeclared implementation is
        a redirect to a traceback; and consent with no ``app_key`` is a
        capability ``resolve`` can never withhold, on an installation that
        holds no app to consent to."""
        declared = Capability.OAUTH in connector.declares

        assert declared is overrides(connector, "authorize_url")
        if declared:
            assert connector.app_key is not None

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_health_checks_are_backed_by_a_check(self, connector: Connector) -> None:
        """``HEALTH_CHECKS`` (or ``WEBHOOKS``) is what puts the Verify step in
        the flow. A connector that declares one and inherits the base
        ``check`` shows the customer an empty checklist, which is a step that
        exists only to be clicked past — and the training effect that teaches
        them to click past the one that matters."""
        if {Capability.HEALTH_CHECKS, Capability.WEBHOOKS} & connector.declares:
            assert StepId.VERIFY in [step.id for step in steps_for(connector.resolve(HOSTED))]
            assert overrides(connector, "check")

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_a_form_is_only_drawn_where_manual_configuration_is_declared(
        self, connector: Connector
    ) -> None:
        """Only in this direction. Web Chat declares ``MANUAL_CONFIGURATION``
        and describes no fields on purpose: for that channel the capability
        means "there is a way to add this here", which ``connectable`` asks
        and every installation answers yes to."""
        if connector.credential_fields():
            assert Capability.MANUAL_CONFIGURATION in connector.declares

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_every_connector_can_actually_be_connected_somewhere(
        self, connector: Connector
    ) -> None:
        """A connector that is connectable on neither kind of installation is
        a row in the picker that leads to a dead end."""
        assert connector.resolve(HOSTED).connectable or connector.resolve(BARE).connectable

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    def test_declared_and_resolved_agree(self, connector: Connector) -> None:
        """Whatever a connector's ``resolve`` does — and SMS's does something
        of its own — it may not invent a capability it never declared, or
        forget to answer for one it did."""
        for context in (HOSTED, BARE):
            resolved = connector.resolve(context)
            assert resolved.channel_type == connector.channel_type
            assert resolved.declares == connector.declares
            assert {state.capability for state in resolved.states} == set(connector.declares)


class TestMetaTurnsOnWhetherTheInstallationHasAnApp:
    """One connector, two rows in an operator's mental model.

    The whole reason capabilities resolve per deployment rather than being
    declared once. A hosted installation holding a Meta app offers consent; a
    self-hosted one that has never been through app review offers the guided
    form — and the second must not be a worse product than the config page
    this flow replaced.
    """

    @pytest.mark.parametrize("channel_type", ["whatsapp", "messenger", "instagram"])
    def test_with_an_app_it_offers_consent_and_a_picker(self, channel_type: str) -> None:
        connector = ConnectorRegistry.get(channel_type)
        assert connector is not None

        resolved = connector.resolve(HOSTED)

        assert resolved.supports(Capability.OAUTH)
        assert resolved.supports(Capability.AUTO_DISCOVERY)
        assert [step.kind for step in steps_for(resolved)] == [
            StepKind.SELECT,
            StepKind.OAUTH_REDIRECT,
            StepKind.RESOURCE_PICKER,
            StepKind.CHECKLIST,
            StepKind.SUMMARY,
        ]

    @pytest.mark.parametrize("channel_type", ["whatsapp", "messenger", "instagram"])
    def test_without_one_it_falls_back_to_the_form(self, channel_type: str) -> None:
        connector = ConnectorRegistry.get(channel_type)
        assert connector is not None

        resolved = connector.resolve(BARE)

        assert not resolved.supports(Capability.OAUTH)
        assert resolved.supports(Capability.MANUAL_CONFIGURATION)
        assert resolved.connectable
        steps = steps_for(resolved)
        assert [step.kind for step in steps][1] is StepKind.FORM
        # Discovery is gone with the grant that would have driven it: there is
        # nothing to enumerate *with*, and a picker built from a pasted
        # credential would be a list of one the customer already named.
        assert StepId.DISCOVER not in [step.id for step in steps]

    def test_it_says_why_in_a_code_the_console_can_translate(self) -> None:
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        resolved = connector.resolve(BARE)

        assert resolved.reason(Capability.OAUTH) == "platform_app_not_configured"
        assert resolved.reason(Capability.AUTO_DISCOVERY) == "platform_app_not_configured"
        # Health checks and webhooks need no provider app, so they survive.
        assert resolved.supports(Capability.HEALTH_CHECKS)
        assert resolved.supports(Capability.WEBHOOKS)

    def test_one_app_key_unlocks_all_three_channels(self) -> None:
        """Not a coincidence and not a convenience: it is why one consent can
        connect WhatsApp, Messenger and Instagram together, and why the Full
        Meta Suite template exists at all."""
        keys = {
            ConnectorRegistry.get(channel_type).app_key  # type: ignore[union-attr]
            for channel_type in ("whatsapp", "messenger", "instagram")
        }

        assert keys == {META_APP}

    def test_the_form_is_still_guided_when_consent_is_unavailable(self) -> None:
        """The fallback path is a worse experience, not an abandonment. Every
        field carries a help key, so a customer on an installation with no
        Meta app still never opens Meta's documentation."""
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        fields = connector.credential_fields()

        assert {field.name for field in fields} == {"phone_number_id", "access_token"}
        assert all(field.help_key for field in fields)

    async def test_the_redirect_uri_comes_from_the_installation_not_the_caller(self) -> None:
        """A client-supplied redirect is an open redirect, and an open
        redirect on an OAuth callback is token theft. The only input a caller
        gets is the opaque ``state``."""
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        url = await connector.authorize_url(state="opaque-state", context=HOSTED)

        assert "redirect_uri=https://engage.example.com/api/v1/channel-oauth/meta/callback" in url
        assert "state=opaque-state" in url
        for scope in connector.scopes:  # type: ignore[attr-defined]
            assert scope in url

    async def test_the_checks_run_on_a_pasted_token_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure the old signature guaranteed. The form path put nothing
        in ``grant``, so on an installation with no Meta app — the only path
        there — every check probed an empty dict and the customer reached the
        summary entirely unverified.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/debug_token")
            assert request.url.params["input_token"] == "TYPED-TOKEN"
            return json_response(
                request,
                {
                    "data": {
                        "scopes": [
                            "whatsapp_business_management",
                            "whatsapp_business_messaging",
                        ]
                    }
                },
            )

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        outcomes = await connector.check(
            Attempt(
                context=BARE,
                inputs={"access_token": "TYPED-TOKEN", "phone_number_id": "PN1"},
            )
        )

        codes = {outcome.code: outcome for outcome in outcomes}
        assert codes["meta.check.scopesGranted"].level == CHECK_OK
        # And nothing blocks: naming the resource on the form is a selection,
        # even though no picker ran.
        assert "meta.check.nothingSelected" not in codes

    async def test_a_typed_token_is_fixed_by_typing_it_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``reauthorize`` on the form path renders a consent button on an
        installation that may hold no Meta app — a button that goes nowhere,
        which is precisely why ``FIX_REENTER`` was added."""
        route(monkeypatch, lambda request: json_response(request, {"data": {"scopes": []}}))
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        typed = await connector.check(Attempt(context=BARE, inputs={"access_token": "T"}))
        consented = await connector.check(Attempt(context=HOSTED, grant={"access_token": "T"}))

        assert [o.fix.kind for o in typed if o.fix] == [FIX_REENTER, FIX_REENTER]
        assert {o.fix.kind for o in consented if o.fix} == {FIX_REAUTHORIZE}


class TestEveryCustomerFacingStringIsATranslationKey:
    """Prose composed on the server is prose that can never be Arabic.

    The rule is stated in three places in the contract — ``CapabilityState``,
    ``Step.title_key``, ``CheckOutcome.code`` — and it is the kind of rule
    that decays one connector at a time, because an English sentence in a
    ``reason`` works perfectly for whoever wrote it. This derives the strings
    from the registry so a connector added later is held to it too.
    """

    def strings_of(self, connector: Connector) -> list[str]:
        found: list[str] = []
        for field in connector.credential_fields():
            found.append(field.label_key)
            if field.help_key:
                found.append(field.help_key)
            found.extend(label_key for _value, label_key in field.options)
        for context in (HOSTED, BARE):
            found.extend(
                state.reason for state in connector.resolve(context).states if state.reason
            )
        return found

    def strings_of_outcomes(self, outcomes: list[CheckOutcome]) -> list[str]:
        found: list[str] = []
        for outcome in outcomes:
            found.append(outcome.code)
            if outcome.fix:
                # ``action_id`` is not customer-facing copy, but it is matched
                # against a literal in ``repair`` and so must be a code too.
                found.extend(
                    value
                    for value in (outcome.fix.instructions_key, outcome.fix.action_id)
                    if value
                )
        return found

    async def every_outcome(
        self, connector: Connector, monkeypatch: pytest.MonkeyPatch
    ) -> list[CheckOutcome]:
        """Run this connector's checklist through every shape it can take.

        Five submissions — nothing typed, a half-filled form either way round,
        a full one, and a full one with an unpickable resource selected —
        against four provider moods: an outage, a refusal, an
        empty-but-successful answer and a plausible one. The half-filled pair
        is what reaches the "you left this out" branches, which is where a
        connector is most likely to reply in prose; between them the matrix
        reaches every branch of every ``check`` in the package, which is what
        makes this a test of the connectors rather than of one path through
        them.
        """
        collected: list[CheckOutcome] = []
        scopes: tuple[str, ...] = getattr(connector, "scopes", ())

        def plausible(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/getMe"):
                return json_response(
                    request,
                    {"ok": True, "result": {"id": 7, "username": "acme_bot"}},
                )
            if path.endswith("/getWebhookInfo"):
                return json_response(
                    request,
                    {
                        "ok": True,
                        "result": {
                            "url": "https://old.example.com/hook",
                            "last_error_message": "Read timeout",
                        },
                    },
                )
            if path.endswith("/debug_token"):
                return json_response(request, {"data": {"scopes": list(scopes)}})
            if path.endswith("IncomingPhoneNumbers.json"):
                number = request.url.params.get("PhoneNumber", "")
                return json_response(
                    request,
                    {
                        "incoming_phone_numbers": [
                            {"sid": "PN1", "phone_number": number, "capabilities": {"sms": False}}
                        ]
                    },
                )
            return json_response(request, {"status": "suspended", "type": "trial"})

        def outage(request: httpx.Request) -> httpx.Response:
            return json_response(request, {}, status=500)

        def rejected(request: httpx.Request) -> httpx.Response:
            return json_response(request, {"message": "authenticate"}, status=401)

        def empty(request: httpx.Request) -> httpx.Response:
            return json_response(request, {})

        unpickable = Resource(id="R1", label="Acme", unavailable_reason="noMessagingRights")
        form = filled_form(connector)
        names = list(form)
        attempts = [
            Attempt(context=HOSTED),
            # Half a form each way: the first field alone gets past the "which
            # carrier?" gate and into the per-carrier requirements, the last
            # alone carries the secret but names no resource.
            Attempt(context=HOSTED, inputs={names[0]: form[names[0]]} if names else {}),
            Attempt(context=HOSTED, inputs={names[-1]: form[names[-1]]} if names else {}),
            Attempt(context=HOSTED, inputs=form),
            Attempt(context=HOSTED, inputs=form, selection=(unpickable,)),
        ]
        for handler in (outage, rejected, empty, plausible):
            for attempt in attempts:
                route(monkeypatch, handler)
                fake_smtp(monkeypatch, connect_error=handler is outage, login_error=True)
                # The contract's other promise about ``check``: outcomes, never
                # an exception. A raise would collapse five findings into
                # whichever happened to be evaluated first.
                collected.extend(await connector.check(attempt))
        return collected

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    async def test_nothing_a_connector_emits_is_a_sentence(
        self, connector: Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcomes = await self.every_outcome(connector, monkeypatch)
        strings = self.strings_of(connector) + self.strings_of_outcomes(outcomes)

        # Guards the guard: a harness that stopped reaching any code at all
        # would otherwise pass this test in silence.
        assert len(strings) >= 3, f"{connector.channel_type} emitted almost nothing to check"
        for value in strings:
            assert looks_like_key(value), f"{connector.channel_type} emits prose: {value!r}"

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    async def test_every_level_and_fix_kind_is_one_of_the_named_ones(
        self, connector: Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The three levels and four fix kinds are named constants so a
        connector cannot invent a fifth by typo — a level the console does not
        recognise is a checklist line rendered as nothing at all."""
        outcomes = await self.every_outcome(connector, monkeypatch)

        assert outcomes, connector.channel_type
        for outcome in outcomes:
            assert outcome.level in {CHECK_OK, CHECK_WARN, CHECK_FAIL}
            if outcome.fix:
                assert outcome.fix.kind in {
                    FIX_ACTION,
                    FIX_REAUTHORIZE,
                    FIX_REENTER,
                    FIX_MANUAL,
                }
                # A button with nothing to invoke, and a connector-handled
                # action nobody named, are the same bug from two sides.
                assert (outcome.fix.kind == FIX_ACTION) is (outcome.fix.action_id is not None)

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    async def test_no_connector_offers_reauthorize_without_oauth(
        self, connector: Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mistake ``FIX_REENTER`` was added to stop, and three connectors
        made independently: a consent button on a channel that has no consent
        screen, which the console cannot send anybody to."""
        outcomes = await self.every_outcome(connector, monkeypatch)

        if Capability.OAUTH not in connector.declares:
            assert not [o for o in outcomes if o.fix and o.fix.kind == FIX_REAUTHORIZE]

    @pytest.mark.parametrize(
        "connector", ConnectorRegistry.all(), ids=lambda c: str(c.channel_type)
    )
    async def test_an_action_fix_names_a_repair_the_connector_answers(
        self, connector: Connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``FIX_ACTION`` is a button the connector handles itself. If
        ``repair`` answers ``not_supported`` for the action the ``Fix`` names,
        the button is a no-op that reports failure — worse than no button."""
        outcomes = await self.every_outcome(connector, monkeypatch)
        actions = {o.fix.action_id for o in outcomes if o.fix and o.fix.action_id}

        for action in actions:
            route(monkeypatch, lambda request: json_response(request, {"ok": True}))
            repair = await connector.repair(
                action=action,
                credentials=filled_form(connector),
                webhook_secret="stored-secret",
                callback_url="https://engage.example.com/api/v1/webhooks/abc",
                context=HOSTED,
            )
            assert repair.reason != "not_supported", f"{connector.channel_type}: {action}"


class TestMetaDiscovery:
    """What the customer owns, as Meta actually answers it.

    Discovery is the step that replaces "find the phone number id in the
    dashboard, it is not the number shown next to it". Every case below is one
    a customer meets in the first week, and each one used to end in a support
    ticket that read "my Page is not in the list".
    """

    async def test_whatsapp_takes_two_hops_to_reach_a_number(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The grant names the business accounts; the numbers hang off those.
        Worth the extra call: the phone number id is the single value a
        customer most often gets wrong by hand, because Meta's dashboard shows
        it beside a display number that is not it."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/debug_token"):
                return json_response(
                    request,
                    {
                        "data": {
                            "granular_scopes": [
                                {
                                    "scope": "whatsapp_business_management",
                                    "target_ids": ["WABA1", "WABA1"],
                                },
                                # A scope for something else entirely, which
                                # must not be mistaken for a business account.
                                {"scope": "pages_show_list", "target_ids": ["PAGE9"]},
                            ]
                        }
                    },
                )
            assert request.url.path.endswith("/WABA1/phone_numbers")
            return json_response(
                request,
                {
                    "data": [
                        {
                            "id": "PN1",
                            "verified_name": "Acme Support",
                            "display_phone_number": "+15551234567",
                            "quality_rating": "GREEN",
                            "code_verification_status": "VERIFIED",
                        },
                        {
                            "id": "PN2",
                            "display_phone_number": "+15559999999",
                            "code_verification_status": "NOT_VERIFIED",
                        },
                    ]
                },
            )

        recorder = route(monkeypatch, handler)
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        resources = await connector.discover(grant={"access_token": "USER-TOKEN"})

        # Two hops, and the duplicate WABA id in the grant is asked about once.
        assert len(recorder.requests) == 2
        assert [resource.id for resource in resources] == ["PN1", "PN2"]
        assert resources[0].label == "Acme Support"
        assert resources[0].detail == {"number": "+15551234567", "quality": "GREEN"}
        assert resources[0].unavailable_reason is None
        # Shown rather than filtered out: a customer who cannot find their
        # number assumes the product is broken, and goes looking for support
        # rather than for the verification screen.
        assert resources[1].unavailable_reason == "numberNotVerified"
        assert resources[1].label == "+15559999999"
        # Subscription happens on the business account, not the number — one
        # of the details that makes configuring this by hand so error-prone,
        # and the reason the parent id is carried to the connect step rather
        # than looked up again.
        assert resources[0].context == {"parent_id": "WABA1", "subscribe_on": "WABA1"}

    async def test_messenger_shows_a_page_it_cannot_message_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Page the customer administers but cannot message from is a real
        and confusing state. Omitting it produces the worst version of the
        conversation: the customer is certain the Page exists, and we are
        certain it does not."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/me/accounts")
            return json_response(
                request,
                {
                    "data": [
                        {
                            "id": "PAGE1",
                            "name": "Acme Support",
                            "category": "Software",
                            "tasks": ["MESSAGING", "ANALYZE"],
                            "access_token": "PAGE1-TOKEN",
                        },
                        {
                            "id": "PAGE2",
                            "name": "Acme Careers",
                            "category": "Recruiter",
                            "tasks": ["ANALYZE"],
                            "access_token": "PAGE2-TOKEN",
                        },
                    ]
                },
            )

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("messenger")
        assert connector is not None

        resources = await connector.discover(grant={"access_token": "USER-TOKEN"})

        assert [resource.id for resource in resources] == ["PAGE1", "PAGE2"]
        assert resources[0].unavailable_reason is None
        assert resources[1].unavailable_reason == "noMessagingRights"
        # The Page token, not the user token: scoped to one Page and it
        # survives the user token being revoked.
        assert resources[0].context["access_token"] == "PAGE1-TOKEN"

    async def test_a_page_the_customer_cannot_message_blocks_the_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discovery shows it; the checklist is where picking it is refused.
        Both halves are needed — showing it without failing on it would let a
        customer connect a channel that can never receive."""
        route(
            monkeypatch,
            lambda request: json_response(request, {"data": {"scopes": []}}),
        )
        connector = ConnectorRegistry.get("messenger")
        assert connector is not None
        unpickable = Resource(
            id="PAGE2", label="Acme Careers", unavailable_reason="noMessagingRights"
        )

        outcomes = await connector.check(
            Attempt(context=HOSTED, grant={"access_token": "T"}, selection=(unpickable,))
        )

        blocked = [o for o in outcomes if o.code == "meta.check.noMessagingRights"]
        assert blocked and blocked[0].level == CHECK_FAIL
        assert blocked[0].params == {"resource": "Acme Careers"}
        assert blocked[0].fix is not None
        assert blocked[0].fix.instructions_key == "connect.meta.fix.noMessagingRights"

    async def test_instagram_drops_pages_with_no_linked_account(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one case where filtering is right rather than hiding: a Page
        with no linked professional account is not an Instagram channel in a
        degraded state, it is not an Instagram channel. This is also the empty
        list a customer with a personal account hits, which is why the copy
        behind the picker has to survive having nothing to show."""

        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                request,
                {
                    "data": [
                        {
                            "id": "PAGE1",
                            "name": "Acme Support",
                            "access_token": "PAGE1-TOKEN",
                            "instagram_business_account": {"id": "IG1", "username": "acme"},
                        },
                        {"id": "PAGE2", "name": "Acme Careers", "access_token": "PAGE2-TOKEN"},
                        {
                            "id": "PAGE3",
                            "name": "Acme Legacy",
                            "instagram_business_account": {},
                        },
                    ]
                },
            )

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("instagram")
        assert connector is not None

        resources = await connector.discover(grant={"access_token": "USER-TOKEN"})

        assert [resource.id for resource in resources] == ["IG1"]
        assert resources[0].label == "acme"
        assert resources[0].detail == {"page": "Acme Support"}
        # Subscription happens on the Page, never on the Instagram account.
        assert resources[0].context["subscribe_on"] == "PAGE1"
        assert resources[0].context["parent_id"] == "PAGE1"
        assert resources[0].context["access_token"] == "PAGE1-TOKEN"

    @pytest.mark.parametrize("channel_type", ["whatsapp", "messenger", "instagram"])
    async def test_discovery_without_a_grant_asks_nobody(
        self, monkeypatch: pytest.MonkeyPatch, channel_type: str
    ) -> None:
        """Reachable whenever the picker is rendered before consent has
        settled. An unauthenticated Graph call would answer with an error the
        customer would then be shown."""
        recorder = route(monkeypatch, lambda request: json_response(request, {}))
        connector = ConnectorRegistry.get(channel_type)
        assert connector is not None

        assert await connector.discover(grant={}) == ()
        assert recorder.requests == []

    async def test_the_token_travels_as_a_parameter_and_never_in_a_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Labels and details are rendered into the picker and, for a failed
        check, into stored diagnostics. A token that reached either would be a
        live credential in a log."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["access_token"] == "USER-TOKEN"
            if request.url.path.endswith("/debug_token"):
                return json_response(
                    request,
                    {
                        "data": {
                            "granular_scopes": [
                                {
                                    "scope": "whatsapp_business_management",
                                    "target_ids": ["WABA1"],
                                }
                            ]
                        }
                    },
                )
            return json_response(request, {"data": [{"id": "PN1", "verified_name": "Acme"}]})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("whatsapp")
        assert connector is not None

        resources = await connector.discover(grant={"access_token": "USER-TOKEN"})

        rendered = [resource.label for resource in resources]
        rendered += [value for resource in resources for value in resource.detail.values()]
        assert "USER-TOKEN" not in " ".join(rendered)


class TestTelegramRegistersItsWebhookAfterTheRowExists:
    """The two defects that made this channel look connected and receive
    nothing — both invisible from the outside, because a bot nobody has
    messaged and a bot whose updates go to a 404 are the same silence."""

    async def test_connect_registers_nothing_and_stores_no_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``connect`` used to derive the channel id as a ``uuid5`` of the bot
        id and register the URL it produced. Telegram accepted it,
        ``getWebhookInfo`` reported a webhook in good order, and every update
        was delivered to a route no row has ever answered."""
        recorder = route(
            monkeypatch,
            lambda request: json_response(
                request, {"ok": True, "result": {"id": 42, "username": "acme_bot"}}
            ),
        )
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(), attempt=Attempt(context=BARE, inputs={"bot_token": "123:AA"})
        )

        assert recorder.paths == ["/bot123:AA/getMe"]
        # Deliberately absent rather than merely unset: a secret in the column
        # before ``setWebhook`` has accepted it is one no delivery would echo.
        assert connection.webhook_secret is None

    async def test_register_webhook_hands_telegram_the_same_secret_it_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole of inbound authentication for this channel. Telegram
        echoes the secret on every delivery and ``verify_signature`` has
        nothing else to work with, so the value in the column and the value
        Telegram holds must be one string — this assertion is that identity."""
        sent: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/bot123:AA/setWebhook"
            sent.append(orjson.loads(request.content))
            return json_response(request, {"ok": True, "result": True})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None
        callback = "https://engage.example.com/api/v1/webhooks/1d3e-channel"

        repair = await connector.register_webhook(
            callback_url=callback, credentials={"bot_token": "123:AA"}, context=BARE
        )

        assert repair.repaired
        assert repair.webhook_secret
        assert sent == [{"url": callback, "secret_token": repair.webhook_secret}]
        # The token did not change, so nothing asks the caller to re-encrypt
        # and rewrite it — and a repair that genuinely rotates a credential
        # stays distinguishable from one that did not.
        assert repair.credentials is None

    async def test_a_refused_registration_returns_no_secret_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A column holding a secret Telegram does not have fails every
        inbound signature check in exactly the way a stale one does."""
        route(monkeypatch, lambda request: json_response(request, {"ok": False}))
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        repair = await connector.register_webhook(
            callback_url="https://engage.example.com/api/v1/webhooks/x",
            credentials={"bot_token": "123:AA"},
            context=BARE,
        )

        assert not repair.repaired
        assert repair.webhook_secret is None
        assert looks_like_key(repair.reason or "")

    async def test_repair_reuses_the_stored_secret_instead_of_minting_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect this replaced, in full: ``repair`` read the secret from
        a credentials key nothing writes, so every press minted a fresh one
        and returned it where nothing reads it. Telegram then signed with a
        secret the stored column did not have and every inbound message was
        discarded as unverifiable — silently, because a channel nobody has
        messaged looks the same."""
        sent: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(orjson.loads(request.content))
            return json_response(request, {"ok": True, "result": True})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        repair = await connector.repair(
            action="reregister_webhook",
            credentials={"bot_token": "123:AA"},
            webhook_secret="the-secret-already-in-the-column",
            callback_url="https://engage.example.com/api/v1/webhooks/x",
            context=BARE,
        )

        assert repair.webhook_secret == "the-secret-already-in-the-column"
        assert sent[0]["secret_token"] == "the-secret-already-in-the-column"

    async def test_repair_never_calls_set_webhook_without_a_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worse than the bug it replaced: Telegram accepts a ``setWebhook``
        with no ``secret_token``, clears the secret, and the URL becomes
        something anyone who guesses it can post updates to."""
        sent: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(orjson.loads(request.content))
            return json_response(request, {"ok": True, "result": True})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        repair = await connector.repair(
            action="reregister_webhook",
            credentials={"bot_token": "123:AA"},
            webhook_secret=None,
            callback_url="https://engage.example.com/api/v1/webhooks/x",
            context=BARE,
        )

        assert sent[0]["secret_token"]
        assert repair.webhook_secret == sent[0]["secret_token"]

    async def test_a_repair_it_cannot_run_answers_rather_than_raising(self) -> None:
        """Pressed from the pre-connect checklist there is no row and
        therefore no callback URL. Inventing one would point Telegram at a
        route that answers 404 — the original defect, by another door."""
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        no_url = await connector.repair(
            action="reregister_webhook",
            credentials={"bot_token": "123:AA"},
            callback_url=None,
            context=BARE,
        )
        unknown = await connector.repair(
            action="something_nobody_offers", credentials={}, context=BARE
        )

        assert not no_url.repaired
        assert looks_like_key(no_url.reason or "")
        assert unknown.reason == "not_supported"

    async def test_the_checklist_names_the_bot_back_to_the_customer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A customer with a staging bot and a real one pastes the wrong token
        roughly half the time, and every symptom appears later and elsewhere:
        messages arriving at a bot nobody watches. One ``getMe`` buys the
        moment they can still change their mind."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/getMe"):
                return json_response(
                    request,
                    {"ok": True, "result": {"id": 42, "username": "acme_bot"}},
                )
            return json_response(request, {"ok": True, "result": {}})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        outcomes = await connector.check(Attempt(context=BARE, inputs={"bot_token": "123:AA"}))

        identity = [o for o in outcomes if o.code == "connect.telegram.check.identity"]
        assert identity and identity[0].params["username"] == "acme_bot"
        assert identity[0].params["botName"] == "@acme_bot"
        # A first-time connect has no webhook yet, and warning that the thing
        # the next step creates does not exist is how a checklist teaches
        # people to click past it.
        assert "connect.telegram.check.delivery" not in {o.code for o in outcomes}


class TestSmsRegistersTheCallbackVerbatim:
    """The URL is the message being signed, so tidying it is a delivery
    failure. ``TwilioGateway.verify_signature`` recomputes its HMAC over the
    URL Twilio requested and the ingress rebuilds that from
    ``public_base_url`` plus the request path — a trailing slash added here
    authenticates every send and fails the signature on every delivery."""

    async def test_it_posts_the_url_it_was_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posted: list[dict[str, list[str]]] = []
        callback = "https://engage.example.com/api/v1/webhooks/9f2c"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                # Twilio keys the number resource by SID, not by the address
                # the customer typed — hence the lookup before the update.
                assert request.url.params["PhoneNumber"] == "+15551234567"
                return json_response(
                    request,
                    {"incoming_phone_numbers": [{"sid": "PN1", "phone_number": "+15551234567"}]},
                )
            assert request.url.path.endswith("/IncomingPhoneNumbers/PN1.json")
            posted.append(parse_qs(request.content.decode()))
            return json_response(request, {"sid": "PN1"})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        repair = await connector.register_webhook(
            callback_url=callback,
            credentials={
                "gateway": "twilio",
                "account_sid": "AC1",
                "auth_token": "t",
                "from_number": "+15551234567",
            },
            context=BARE,
        )

        assert repair.repaired
        assert posted == [{"SmsUrl": [callback], "SmsMethod": ["POST"]}]
        # A number left on GET delivers the message in the query string, where
        # a form-encoded parse finds nothing it can even attribute to a sender.
        assert repair.webhook_secret is None

    async def test_a_number_that_moved_accounts_is_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This hook runs after the row exists. Aborting a connect whose
        outbound already works, over a callback the customer can also paste by
        hand, would be the wrong trade."""
        route(
            monkeypatch,
            lambda request: json_response(request, {"incoming_phone_numbers": []}),
        )
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        repair = await connector.register_webhook(
            callback_url="https://engage.example.com/api/v1/webhooks/9f2c",
            credentials={
                "gateway": "twilio",
                "account_sid": "AC1",
                "auth_token": "t",
                "from_number": "+15551234567",
            },
            context=BARE,
        )

        assert not repair.repaired
        assert looks_like_key(repair.reason or "")

    async def test_a_rejected_account_and_an_unlistable_number_are_different_findings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both calls carry the same credentials, so once the account call has
        returned 200 those credentials are established fact. Reporting a 404
        on the number list as a rejection sent the customer back to retype an
        account SID that had just been proved correct, and left the real cause
        unnamed."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("IncomingPhoneNumbers.json"):
                return json_response(request, {"message": "not found"}, status=404)
            return json_response(request, {"status": "active", "type": "full"})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        outcomes = await connector.check(
            Attempt(
                context=BARE,
                inputs={
                    "gateway": "twilio",
                    "account_sid": "AC1",
                    "auth_token": "t",
                    "from_number": "+15551234567",
                },
            )
        )

        codes = {outcome.code: outcome for outcome in outcomes}
        assert codes["connect.sms.check.credentialsVerified"].level == CHECK_OK
        assert codes["connect.sms.check.numberUnverified"].level == CHECK_WARN
        assert "connect.sms.check.credentialsRejected" not in codes
        assert codes["connect.sms.check.numberUnverified"].params["status"] == "404"

    async def test_a_carrier_that_registers_promises_nothing_is_left_to_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The warning that survived is now per carrier rather than per
        channel: a customer whose gateway can be pointed at us should not be
        told to go and paste a URL into a console."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("IncomingPhoneNumbers.json"):
                return json_response(
                    request,
                    {
                        "incoming_phone_numbers": [
                            {
                                "sid": "PN1",
                                "phone_number": "+15551234567",
                                "capabilities": {"sms": True},
                            }
                        ]
                    },
                )
            return json_response(request, {"status": "active", "type": "full"})

        route(monkeypatch, handler)
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        outcomes = await connector.check(
            Attempt(
                context=BARE,
                inputs={
                    "gateway": "twilio",
                    "account_sid": "AC1",
                    "auth_token": "t",
                    "from_number": "+15551234567",
                },
            )
        )

        codes = {outcome.code for outcome in outcomes}
        assert "connect.sms.check.webhookAutomatic" in codes
        assert "connect.sms.check.webhookManualSetup" not in codes
        assert "connect.sms.check.numberVerified" in codes


class TestTheNameTheCustomerChoseSurvives:
    """``display_name`` is stored verbatim and rendered forever — channel
    list, reports, PDF and Excel exports. A connector that drops it names
    every channel after its own mailbox or handle regardless of what the
    customer typed, which was invisible until the attempt carried the field.
    """

    async def test_telegram_prefers_the_typed_name_over_the_handle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        route(
            monkeypatch,
            lambda request: json_response(
                request, {"ok": True, "result": {"id": 42, "username": "acme_bot"}}
            ),
        )
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None

        named = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=BARE, inputs={"bot_token": "1:A"}, display_name="  Support Bot  "
            ),
        )
        unnamed = await connector.connect(
            company_id=uuid4(), attempt=Attempt(context=BARE, inputs={"bot_token": "1:A"})
        )

        assert named[0].display_name == "Support Bot"
        # ``@handle`` and not ``first_name``: two channels run from one
        # BotFather account are frequently both called the company's name.
        assert unnamed[0].display_name == "@acme_bot"

    async def test_email_falls_back_to_the_mailbox_and_never_to_a_sentence(self) -> None:
        connector = ConnectorRegistry.get("email")
        assert connector is not None
        form = {"smtp_host": "smtp.example.com", "from_address": "support@example.com"}

        named = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(context=BARE, inputs=form, display_name="Support Inbox"),
        )
        unnamed = await connector.connect(
            company_id=uuid4(), attempt=Attempt(context=BARE, inputs=form)
        )

        assert named[0].display_name == "Support Inbox"
        # Both fallbacks are values the customer supplied, so nothing
        # untranslatable reaches a column that is rendered into an export.
        assert unnamed[0].display_name == "support@example.com"

    async def test_sms_falls_back_to_the_number_the_agent_will_recognise(self) -> None:
        connector = ConnectorRegistry.get("sms")
        assert connector is not None

        (connection,) = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=BARE,
                inputs={
                    "gateway": "twilio",
                    "account_sid": "AC1",
                    "auth_token": "t",
                    "from_number": "+15551234567",
                },
            ),
        )

        assert connection.display_name == "+15551234567"

    async def test_meta_only_honours_one_name_for_one_resource(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One typed name cannot describe three channels, and silently giving
        all three the same one produces a channel list nobody can read."""
        route(monkeypatch, lambda request: json_response(request, {"success": True}))
        connector = ConnectorRegistry.get("messenger")
        assert connector is not None
        pages = (
            Resource(id="PAGE1", label="Acme Support", context={"access_token": "T1"}),
            Resource(id="PAGE2", label="Acme Careers", context={"access_token": "T2"}),
        )

        one = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=HOSTED,
                grant={"access_token": "USER"},
                selection=pages[:1],
                display_name="Front Desk",
            ),
        )
        both = await connector.connect(
            company_id=uuid4(),
            attempt=Attempt(
                context=HOSTED,
                grant={"access_token": "USER"},
                selection=pages,
                display_name="Front Desk",
            ),
        )

        assert [c.display_name for c in one] == ["Front Desk"]
        assert [c.display_name for c in both] == ["Acme Support", "Acme Careers"]

    async def test_web_chat_falls_back_to_a_key_rather_than_a_slug(self) -> None:
        """The least bad option rather than a good one: this is the one
        connector with no provider-side name to borrow, so the fallback is a
        key that at least resolves in the console. The real fix is upstream —
        the naming input should require a value."""
        connector = ConnectorRegistry.get("web_chat")
        assert connector is not None

        (connection,) = await connector.connect(company_id=uuid4(), attempt=Attempt(context=BARE))

        assert looks_like_key(connection.display_name)
        assert connection.display_name != "web_chat"


class TestNoNetworkCallLacksATimeout:
    """A client built without one waits as long as the kernel allows.

    On the Verify step that is a customer watching a spinner until they give
    up on a two-minute promise; on ``register_webhook`` it is a request
    holding a worker while a carrier black-holes the connection. Checked two
    ways, because neither alone is enough: the source scan covers the branches
    no test reaches, and the runtime assertion covers a client constructed by
    something the scan cannot see.
    """

    #: Everything in this package that opens a socket. ``aiosmtplib.SMTP`` is
    #: here for the same reason ``httpx.AsyncClient`` is — email's probe is a
    #: network call that happens not to be HTTP.
    CONSTRUCTORS = frozenset({"AsyncClient", "Client", "SMTP", "SMTP_SSL"})

    def connector_modules(self) -> list[Path]:
        """Derived from the package directory, so a connector added tomorrow
        is scanned without this file being edited."""
        directory = Path(connectors_package.__file__).parent
        return sorted(path for path in directory.glob("*.py") if path.name != "__init__.py")

    def test_every_client_in_the_package_is_constructed_with_one(self) -> None:
        checked = 0
        for path in self.connector_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name not in self.CONSTRUCTORS:
                    continue
                checked += 1
                assert any(
                    keyword.arg == "timeout" for keyword in node.keywords
                ), f"{path.name}:{node.lineno} opens {name} with no timeout"
        # Guards the scan itself: a rename that stopped matching anything
        # would otherwise make this test pass by finding nothing.
        assert checked >= 4, "the timeout scan matched almost nothing — has it stopped working?"

    async def test_the_clients_the_connectors_actually_build_carry_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = route(monkeypatch, lambda request: json_response(request, {"ok": True}))
        for channel_type, attempt in (
            ("telegram", Attempt(context=BARE, inputs={"bot_token": "1:A"})),
            ("whatsapp", Attempt(context=BARE, inputs={"access_token": "T"})),
            (
                "sms",
                Attempt(
                    context=BARE,
                    inputs={
                        "gateway": "twilio",
                        "account_sid": "AC1",
                        "auth_token": "t",
                        "from_number": "+1555",
                    },
                ),
            ),
        ):
            connector = ConnectorRegistry.get(channel_type)
            assert connector is not None
            await connector.check(attempt)

        assert recorder.client_kwargs
        for kwargs in recorder.client_kwargs:
            assert kwargs.get("timeout") is not None

    async def test_the_email_probe_bounds_its_own_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corporate relay that accepts the TCP connection and never
        completes the TLS handshake is the ordinary way this hangs."""
        opened = fake_smtp(monkeypatch)
        connector = ConnectorRegistry.get("email")
        assert connector is not None

        await connector.check(
            Attempt(context=BARE, inputs={"smtp_host": "smtp.example.com", "smtp_port": "587"})
        )

        assert opened and all(kwargs.get("timeout") for kwargs in opened)
