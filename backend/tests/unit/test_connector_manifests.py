"""Every connector must be honest about itself.

The manifest is the contract with the console: the wizard renders what a
connector declares and knows nothing else about it. That makes a *wrong*
manifest worse than a missing feature — the console will confidently draw a
form nobody validates, a repair button that does nothing, or a checklist code
it has no words for.

So these tests are all one shape: **derive the expectation from the registry**
and hold every connector to it. Nothing here names a channel, which means a
connector added tomorrow is covered the moment it registers, without anybody
remembering to extend a list.
"""

from __future__ import annotations

import inspect
import re

import pytest

from blinkengage.domain.connector import Connector, DeploymentContext
from blinkengage.domain.connector_diagnostics import DiagnosticKey, DiagnosticStatus
from blinkengage.domain.connector_lifecycle import (
    BLOCKS_NEW_CONNECTIONS,
    WARNS,
    Availability,
    ChannelFeature,
    Direction,
    LifecycleState,
    Maturity,
    Version,
    VersionInfo,
    effective_state,
)
from blinkengage.domain.connector_manifest import (
    BLOCKING_CODES,
    AuthMethod,
    ConnectorCategory,
    ValidationCode,
)
from blinkengage.domain.connectors import Capability, StepId, StepKind, steps_for
from blinkengage.infrastructure.connectors import ConnectorRegistry

HOSTED = DeploymentContext("https://engage.example.com", frozenset({"meta"}))
BARE = DeploymentContext("https://engage.example.com")

#: What this build is. Connectors shipped in-tree must all run on it.
PLATFORM_VERSION = "1.0.0-beta.5"

CONNECTORS = ConnectorRegistry.all()

#: A translation key: dotted, no spaces, no sentence punctuation. Crude on
#: purpose — it catches prose, which is the failure that matters, without
#: pretending to validate that the key exists.
KEY = re.compile(r"^[a-zA-Z0-9_.]+$")

#: Codes that are deliberately not blocking, each for its own reason. Listed
#: here so ``test_every_code_is_classified`` fails on a code nobody decided
#: about — the dangerous default, since an unclassified code would let a
#: customer connect through a genuine failure.
NON_BLOCKING = {
    ValidationCode.OK,
    ValidationCode.ADVISORY,
    # The provider's problem, not the customer's setup. Blocking would mean
    # a customer cannot connect during somebody else's outage, with nothing
    # they could do about it.
    ValidationCode.PROVIDER_UNREACHABLE,
    ValidationCode.RATE_LIMITED,
    # Registration happens *after* the row exists, so during setup this is
    # always true and about to stop being. Blocking here would block every
    # first connection on a channel that registers its own webhook.
    ValidationCode.WEBHOOK_NOT_REGISTERED,
}


def ids(connectors: tuple[Connector, ...]) -> list[str]:
    return [c.channel_type for c in connectors]


class TestTheRegistryIsPopulated:
    def test_connectors_are_registered(self) -> None:
        """A suite that iterates an empty registry passes forever and proves
        nothing. This is the tripwire under every test below."""
        assert len(CONNECTORS) >= 5, ids(CONNECTORS)


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestEveryManifestIsComplete:
    def test_it_identifies_itself(self, connector: Connector) -> None:
        manifest = connector.manifest

        assert manifest.channel_type == connector.channel_type
        assert manifest.name_key and manifest.description_key
        assert manifest.icon
        assert isinstance(manifest.category, ConnectorCategory)

    def test_it_says_how_to_authenticate(self, connector: Connector) -> None:
        """A connector with no auth method is one the wizard cannot start."""
        assert connector.manifest.auth_methods

    def test_capabilities_come_from_the_manifest(self, connector: Connector) -> None:
        """Two places to state a capability is one place for them to
        disagree, and a disagreement would be invisible until a flow came out
        the wrong shape."""
        assert connector.declares == connector.manifest.capabilities

    def test_a_credentials_method_means_a_credentials_form(
        self, connector: Connector
    ) -> None:
        """And the reverse. A connector offering the form but declaring no
        fields renders an empty step; one declaring fields but not the method
        collects values the flow never asked for.

        Web Chat is the deliberate exception and states it: it declares the
        method with no fields because it genuinely needs nothing.
        """
        manifest = connector.manifest
        if AuthMethod.CREDENTIALS in manifest.auth_methods:
            assert manifest.required_credentials, connector.channel_type
        if manifest.required_credentials:
            assert AuthMethod.CREDENTIALS in manifest.auth_methods, connector.channel_type

    def test_oauth_is_declared_consistently(self, connector: Connector) -> None:
        manifest = connector.manifest
        oauth = AuthMethod.OAUTH in manifest.auth_methods

        assert oauth == (Capability.OAUTH in manifest.capabilities)
        if oauth:
            # Consent needs an app to consent to, and a scope list to ask for.
            assert connector.app_key, connector.channel_type
            assert manifest.required_permissions, connector.channel_type

    def test_discovery_is_declared_with_something_to_discover(
        self, connector: Connector
    ) -> None:
        """A picker with nothing described renders a list with no heading and
        no explanation when it comes back empty — which is the case customers
        actually hit."""
        if Capability.AUTO_DISCOVERY in connector.manifest.capabilities:
            assert connector.manifest.required_resources, connector.channel_type

    def test_a_verify_step_has_something_to_show(self, connector: Connector) -> None:
        """The console draws the checklist before it has answers, so a
        connector whose flow includes Verify must say what is being verified
        — otherwise the step is a blank panel that reads as a hang."""
        flow = steps_for(connector.resolve(BARE), declared=connector.manifest.steps)
        if any(step.id is StepId.VERIFY for step in flow):
            assert connector.manifest.verification_steps, connector.channel_type


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestDeclarationsMatchImplementations:
    """A capability is a promise. These check the promise is kept."""

    @staticmethod
    def _overrides(connector: Connector, name: str) -> bool:
        return getattr(type(connector), name) is not getattr(Connector, name)

    def test_automatic_webhook_registration_registers_something(
        self, connector: Connector
    ) -> None:
        """The capability that was undeliverable until the contract grew a
        post-persist hook. A connector declaring it and inheriting the base's
        refusal promises inbound that never arrives.

        Shared-webhook connectors are exempt and say so: their callback is
        configured once on the provider app, so there is nothing per channel
        to register.
        """
        manifest = connector.manifest
        if Capability.AUTOMATIC_WEBHOOK_REGISTRATION not in manifest.capabilities:
            return
        if Capability.SHARED_WEBHOOK in manifest.capabilities:
            return
        assert self._overrides(connector, "register_webhook"), connector.channel_type

    def test_discovery_is_implemented_where_declared(self, connector: Connector) -> None:
        if Capability.AUTO_DISCOVERY in connector.manifest.capabilities:
            assert self._overrides(connector, "discover"), connector.channel_type

    def test_oauth_is_implemented_where_declared(self, connector: Connector) -> None:
        if Capability.OAUTH in connector.manifest.capabilities:
            assert self._overrides(connector, "authorize_url"), connector.channel_type

    def test_every_declared_repair_is_answerable(self, connector: Connector) -> None:
        """A declared repair the connector cannot perform is a button that
        does nothing — worse than no button, because the customer believes
        they have tried."""
        if connector.manifest.repair_actions:
            assert self._overrides(connector, "repair"), connector.channel_type

    def test_a_repair_referenced_by_validation_is_declared(
        self, connector: Connector
    ) -> None:
        """The console renders a repair button from the *manifest*, so a
        finding pointing at an undeclared action offers a fix nothing can
        draw. Read off the source rather than run, since reaching every
        branch of a validator needs a provider on the other end."""
        source = inspect.getsource(type(connector))
        declared = {action.id for action in connector.manifest.repair_actions}
        for referenced in re.findall(r"repair_action=([A-Za-z_][A-Za-z0-9_]*)", source):
            # A constant name, resolved against the module it came from.
            module = inspect.getmodule(type(connector))
            value = getattr(module, referenced, None)
            if isinstance(value, str):
                assert value in declared, f"{connector.channel_type}: {value}"


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestNothingCustomerFacingIsProse:
    """Prose from the server can only ever be English, and this product
    ships Arabic. Every one of these is a key the console translates."""

    def test_manifest_copy_keys(self, connector: Connector) -> None:
        manifest = connector.manifest
        keys = [
            manifest.name_key,
            manifest.description_key,
            *(spec.label_key for spec in manifest.required_credentials),
            *(spec.help_key or "x" for spec in manifest.required_credentials),
            *(spec.title_key for spec in manifest.required_resources),
            *(spec.empty_key for spec in manifest.required_resources),
            *(spec.title_key for spec in manifest.verification_steps),
            *(action.title_key for action in manifest.repair_actions),
            *(action.description_key for action in manifest.repair_actions),
            *(link.key for link in manifest.documentation),
        ]

        for key in keys:
            assert KEY.match(key), f"{connector.channel_type}: {key!r}"

    def test_documentation_links_are_real_urls(self, connector: Connector) -> None:
        for link in connector.manifest.documentation:
            assert link.url.startswith("https://"), connector.channel_type

    def test_placeholders_are_shapes_not_sentences(self, connector: Connector) -> None:
        """A placeholder is the one string that legitimately is not a key —
        it shows the *shape* of a value, which is the same in every language.
        It must not become a sentence."""
        for spec in connector.manifest.required_credentials:
            if spec.placeholder:
                assert " " not in spec.placeholder.strip(), connector.channel_type


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestValidationCodesAreDeclared:
    def test_every_declared_code_is_a_real_one(self, connector: Connector) -> None:
        for code in connector.manifest.declared_codes:
            assert isinstance(code, ValidationCode)

    def test_the_manifest_declares_the_codes_the_source_returns(
        self, connector: Connector
    ) -> None:
        """The console pre-resolves copy from ``verification_steps``, so a
        code this connector can return but never declared is a raw slug in
        front of a customer at the worst possible moment.

        Read off the source rather than executed: reaching every branch of a
        validator needs a provider on the other end, and the point here is
        completeness rather than behaviour.
        """
        source = inspect.getsource(inspect.getmodule(type(connector)))
        used = {
            ValidationCode[name]
            for name in re.findall(r"ValidationCode\.([A-Z_]+)", source)
            if name in ValidationCode.__members__
        }
        # A shared module declares codes across several connectors, so the
        # union of that module's manifests is the fair comparison.
        module_name = type(connector).__module__
        declared: set[ValidationCode] = set()
        for other in CONNECTORS:
            if type(other).__module__ == module_name:
                declared |= other.manifest.declared_codes

        assert used <= declared, (
            f"{connector.channel_type} can return {sorted(c.value for c in used - declared)} "
            "but never declared them"
        )


class TestBlockingIsDecidedCentrally:
    def test_a_code_blocks_the_same_way_everywhere(self) -> None:
        """One channel must not block on something another waves through —
        that inconsistency is invisible to the customer and unexplainable
        when they notice it."""
        assert ValidationCode.OK not in BLOCKING_CODES
        assert ValidationCode.ADVISORY not in BLOCKING_CODES
        assert ValidationCode.INVALID_TOKEN in BLOCKING_CODES

    def test_advisory_never_blocks(self) -> None:
        """A checklist that blocked on advice would train customers to click
        past it, which is how the real failure gets missed."""
        from blinkengage.domain.connector_manifest import ValidationResult, blocking

        results = (
            ValidationResult(ValidationCode.OK),
            ValidationResult(ValidationCode.ADVISORY),
        )

        assert blocking(results) == ()

    def test_every_code_is_classified(self) -> None:
        """A code nobody decided about defaults to non-blocking, which is the
        dangerous direction: a genuine failure would let the customer
        connect."""
        unclassified = {
            code
            for code in ValidationCode
            if code not in BLOCKING_CODES
            and code not in NON_BLOCKING
        }

        assert unclassified == set(), sorted(c.value for c in unclassified)


class TestTheManifestDrivesTheFlow:
    def test_a_declared_flow_wins(self) -> None:
        """The inversion the manifest exists for: the connector decides which
        steps exist, and the wizard only renders them."""
        from blinkengage.domain.connectors import ConnectorProfile

        profile = ConnectorProfile(channel_type="x", declares=frozenset())
        declared = ((StepId.SELECT, StepKind.SELECT), (StepId.CONNECT, StepKind.SUMMARY))

        assert [s.id for s in steps_for(profile, declared=declared)] == [
            StepId.SELECT,
            StepId.CONNECT,
        ]

    def test_no_connector_needs_one_yet(self) -> None:
        """Deriving from capabilities means a connector cannot forget a step,
        so an explicit flow should stay rare. If this starts failing, the
        derivation has stopped fitting and that is worth knowing."""
        overridden = [c.channel_type for c in CONNECTORS if c.manifest.steps]

        assert overridden == []

    def test_meta_changes_shape_with_the_installation(self) -> None:
        """One manifest, two flows — and the manifest did not have to say so,
        because capability resolution already did."""
        meta = ConnectorRegistry.get("whatsapp")
        assert meta is not None

        hosted = steps_for(meta.resolve(HOSTED))
        bare = steps_for(meta.resolve(BARE))

        assert hosted[1].kind is StepKind.OAUTH_REDIRECT
        assert bare[1].kind is StepKind.FORM
        assert StepId.DISCOVER not in [s.id for s in bare]


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestLifecycleAndVersions:
    """A connector must be honest about how finished it is."""

    def test_it_declares_a_maturity(self, connector: Connector) -> None:
        assert isinstance(connector.manifest.maturity, Maturity)

    def test_it_declares_all_three_versions(self, connector: Connector) -> None:
        """Its own code, the provider's API, and the platform it needs —
        three things people conflate, so each is stated."""
        versions = connector.manifest.versions

        assert Version.parse(versions.connector)
        assert Version.parse(versions.minimum_platform)
        # ``api`` is free text because providers version themselves however
        # they like — ``v21.0``, ``2010-04-01``, or nothing at all. Empty is
        # legitimate; a connector that invented one would be manufacturing
        # the deprecation risk this field exists to communicate.
        assert isinstance(versions.api, str)

    def test_a_connector_needing_a_newer_platform_is_not_offered(
        self, connector: Connector
    ) -> None:
        """The warning an administrator needs, before a customer meets a
        flow that cannot finish."""
        from_future = DeploymentContext(
            "https://engage.example.com",
            frozenset({"meta"}),
            platform_version="0.9.0",
        )
        needs_newer = not connector.manifest.versions.supported_by("0.9.0")

        if needs_newer:
            assert not connector.resolve(from_future).connectable

    def test_it_is_offered_on_this_platform(self, connector: Connector) -> None:
        """Nothing shipped in-tree may require a platform this build is not.
        A connector nobody can use is a connector nobody will notice is
        broken."""
        assert connector.manifest.versions.supported_by(PLATFORM_VERSION)


class TestLifecycleResolution:
    """Two axes, one badge."""

    def test_maturity_shows_through_when_nothing_is_wrong(self) -> None:
        assert (
            effective_state(Maturity.BETA, Availability.AVAILABLE)
            is LifecycleState.BETA
        )

    def test_availability_wins(self) -> None:
        """"We have turned this off" is more urgent and more actionable than
        "this code is mature", and showing the maturity badge on a connector
        nobody can use answers a question the customer did not ask."""
        assert (
            effective_state(Maturity.PRODUCTION, Availability.MAINTENANCE)
            is LifecycleState.MAINTENANCE
        )
        assert (
            effective_state(Maturity.DEPRECATED, Availability.DISABLED)
            is LifecycleState.DISABLED
        )

    def test_a_disabled_connector_refuses_new_connections(self) -> None:
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None
        off = DeploymentContext(
            "https://engage.example.com",
            availability={"telegram": Availability.DISABLED},
        )

        resolved = connector.resolve(off)

        assert resolved.lifecycle is LifecycleState.DISABLED
        assert not resolved.connectable

    def test_maintenance_refuses_too(self) -> None:
        """A connection made during an outage fails in a way the customer
        blames on themselves."""
        connector = ConnectorRegistry.get("telegram")
        assert connector is not None
        down = DeploymentContext(
            "https://engage.example.com",
            availability={"telegram": Availability.MAINTENANCE},
        )

        assert not connector.resolve(down).connectable

    def test_one_connector_going_dark_does_not_take_the_others(self) -> None:
        """Availability is keyed per channel type, so an operator disabling
        one is not an outage."""
        off = DeploymentContext(
            "https://engage.example.com",
            availability={"telegram": Availability.DISABLED},
        )

        others = [
            c.channel_type
            for c in CONNECTORS
            if c.channel_type != "telegram" and not c.resolve(off).connectable
        ]

        assert others == []

    def test_preview_and_beta_warn_without_blocking(self) -> None:
        """A customer may connect something unfinished as long as they were
        told. Blocking would make Preview useless as a release stage."""
        for maturity in (Maturity.PREVIEW, Maturity.BETA, Maturity.DEPRECATED):
            state = effective_state(maturity, Availability.AVAILABLE)
            assert state in WARNS
            assert state not in BLOCKS_NEW_CONNECTIONS

    def test_end_of_life_blocks(self) -> None:
        assert LifecycleState.END_OF_LIFE in BLOCKS_NEW_CONNECTIONS

    def test_every_state_is_decided_about(self) -> None:
        """A state nobody classified silently allows connections, which is
        the dangerous direction."""
        undecided = (
            set(LifecycleState)
            - BLOCKS_NEW_CONNECTIONS
            - WARNS
            - {LifecycleState.AVAILABLE, LifecycleState.PRODUCTION}
        )

        assert undecided == set(), sorted(s.value for s in undecided)


class TestVersionComparison:
    def test_a_prerelease_satisfies_its_own_release(self) -> None:
        """Blink Engage is ``1.0.0-beta.5``. If a pre-release did not satisfy
        ``1.0.0``, no connector could declare a minimum until the first
        stable release — so every connector would have to declare ``0.x`` and
        the field would mean nothing."""
        assert Version.parse("1.0.0-beta.5").satisfies(Version.parse("1.0.0"))

    def test_older_platforms_do_not_satisfy(self) -> None:
        assert not Version.parse("0.9.9").satisfies(Version.parse("1.0.0"))

    def test_an_unparseable_version_does_not_hide_a_connector(self) -> None:
        """A connector that vanished because somebody's build stamped a
        non-semver string is a worse failure than one that appears and is
        never used."""
        assert VersionInfo(minimum_platform="not-a-version").supported_by("1.0.0")
        assert VersionInfo(minimum_platform="1.0.0").supported_by("nightly")


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestTheFeatureMatrixIsHonest:
    def test_features_come_from_the_closed_set(self, connector: Connector) -> None:
        """Free strings let one connector say "images" and another "media",
        and a matrix built from that is a matrix that lies."""
        for support in connector.manifest.supported_features:
            assert isinstance(support.feature, ChannelFeature)
            assert isinstance(support.direction, Direction)

    def test_no_feature_is_claimed_twice(self, connector: Connector) -> None:
        """Two rows for one feature is two answers to one question, and the
        console renders whichever it reaches first."""
        features = [s.feature for s in connector.manifest.supported_features]

        assert len(features) == len(set(features)), connector.channel_type

    def test_a_channel_that_connects_can_carry_something(
        self, connector: Connector
    ) -> None:
        assert connector.manifest.supported_features, connector.channel_type

    def test_sending_and_receiving_are_declared_in_one_direction_each(
        self, connector: Connector
    ) -> None:
        """``SEND_MESSAGES`` is outbound by its own name. Declaring it
        ``BOTH`` says nothing and reads as carelessness."""
        for support in connector.manifest.supported_features:
            if support.feature is ChannelFeature.SEND_MESSAGES:
                assert support.direction is Direction.OUTBOUND, connector.channel_type
            if support.feature is ChannelFeature.RECEIVE_MESSAGES:
                assert support.direction is Direction.INBOUND, connector.channel_type

    def test_notes_are_translation_keys(self, connector: Connector) -> None:
        for support in connector.manifest.supported_features:
            if support.note_key:
                assert KEY.match(support.note_key), connector.channel_type


class TestTheMatrixMatchesTheProviders:
    """The check worth the most: a matrix that overclaims is worse than no
    matrix, because a customer picks a channel for a feature that silently
    does nothing.

    Spot-checked against facts read off the transport providers by hand.
    Deriving them would make the comparison tautological.
    """

    def test_sms_receives_media_and_cannot_send_it(self) -> None:
        """``SmsProvider.send_message`` raises on an outbound attachment.
        This is the exact case ``Direction`` was added for — one tick against
        "Media" would be wrong whichever way the reader assumed."""
        sms = ConnectorRegistry.get("sms")
        assert sms is not None

        media = sms.manifest.supports(ChannelFeature.MEDIA)

        assert media is None or media.direction is Direction.INBOUND

    def test_whatsapp_does_not_claim_typing(self) -> None:
        """``WhatsAppProvider.typing_indicator`` is a documented no-op — the
        Cloud API has no freestanding toggle — while Messenger and Instagram
        genuinely send ``sender_action``."""
        whatsapp = ConnectorRegistry.get("whatsapp")
        messenger = ConnectorRegistry.get("messenger")
        assert whatsapp is not None and messenger is not None

        assert whatsapp.manifest.supports(ChannelFeature.TYPING_INDICATORS) is None
        assert messenger.manifest.supports(ChannelFeature.TYPING_INDICATORS) is not None

    def test_only_email_claims_no_typing_and_real_threading(self) -> None:
        """Email is the one provider with
        ``supports_invisible_reply_threading``."""
        email = ConnectorRegistry.get("email")
        assert email is not None

        assert email.manifest.supports(ChannelFeature.THREADING) is not None
        assert email.manifest.supports(ChannelFeature.TYPING_INDICATORS) is None

    def test_nobody_claims_calls(self) -> None:
        """No provider in this build implements voice or video. A tick here
        would be the most visible possible overclaim."""
        claimed = [
            c.channel_type
            for c in CONNECTORS
            if c.manifest.supports(ChannelFeature.VOICE_CALLS)
            or c.manifest.supports(ChannelFeature.VIDEO_CALLS)
        ]

        assert claimed == []


class TestDiagnosticsAreNeverInvented:
    """The failure that makes a support panel worse than no panel.

    A green tick on something nobody measured sends an engineer away from the
    actual problem, with more confidence than they started with. Each of
    these pins a case where that nearly shipped.
    """

    async def test_a_huge_expiry_does_not_blank_the_report(self) -> None:
        """A timestamp too large for the platform clock raises rather than
        returning something wrong — and this runs outside the caller's guard,
        so it took the connector's whole half of the report with it and left
        four rows silently blank."""
        from blinkengage.infrastructure.connectors.meta import WhatsAppConnector, _Probe

        data = {"is_valid": True, "expires_at": 99999999999999999, "scopes": []}
        probe = _Probe(body={"data": data}, reached=True)

        found = WhatsAppConnector()._authentication(probe, data)

        assert [d.status for d in found] == [DiagnosticStatus.UNKNOWN]

    def test_throttling_is_not_a_rejected_credential(self) -> None:
        """Graph returns rate limits and transient platform errors in the
        same envelope shape as a bad token. Reporting those as a failure
        sends an engineer to rotate a credential that works — during an
        outage, while a customer waits."""
        from blinkengage.infrastructure.connectors.meta import _is_transient, _Probe

        assert _is_transient(_Probe(reached=True, error_code=4))
        assert _is_transient(_Probe(reached=True, error_code=32))
        # 190 is an expired or invalid access token: genuinely the
        # customer's problem, and genuinely a failure.
        assert not _is_transient(_Probe(reached=True, error_code=190))
        assert not _is_transient(_Probe(reached=True))

    async def test_a_configured_imap_host_is_not_a_working_mailbox(self) -> None:
        """The one row a support engineer reads as "is anything arriving?".
        A host set with a blank password would have shown green while nothing
        arrived — and nothing else covers it, since the platform's half never
        contributes this key and the connector wins the merge."""
        connector = ConnectorRegistry.get("email")
        assert connector is not None

        report = await connector.diagnose(
            credentials={"smtp_host": "smtp.example.com", "imap_host": "imap.example.com"},
            context=BARE,
        )
        webhook = report.get(DiagnosticKey.WEBHOOK_STATUS)

        assert webhook is not None
        assert webhook.status is not DiagnosticStatus.OK


@pytest.mark.parametrize("connector", CONNECTORS, ids=ids(CONNECTORS))
class TestDiagnosticsContract:
    async def test_it_never_raises(self, connector: Connector) -> None:
        """Hostile input, because a panel that 500s tells a support engineer
        nothing at the moment they most need it."""
        for credentials in (
            {},
            {"bot_token": "no\nnewlines\tallowed"},
            {"access_token": "", "phone_number_id": None},
            {"smtp_host": "", "smtp_port": "not-a-port"},
            {"gateway": "nonexistent", "account_sid": "x"},
        ):
            report = await connector.diagnose(credentials=credentials, context=BARE)
            assert report.channel_type in {connector.channel_type, ""}

    async def test_it_only_answers_keys_it_can_measure(
        self, connector: Connector
    ) -> None:
        """With no credentials there is nothing to ask a provider, so nothing
        may come back OK. A connector reporting health from an empty dict is
        reporting something it did not measure."""
        report = await connector.diagnose(credentials={}, context=BARE)

        invented = [
            item.key.value
            for item in report.items
            if item.status is DiagnosticStatus.OK
        ]

        assert invented == [], f"{connector.channel_type} invented {invented}"

    async def test_repairs_it_points_at_are_declared(self, connector: Connector) -> None:
        report = await connector.diagnose(credentials={}, context=BARE)
        declared = {action.id for action in connector.manifest.repair_actions}

        for item in report.items:
            if item.repair_action:
                assert item.repair_action in declared, connector.channel_type
