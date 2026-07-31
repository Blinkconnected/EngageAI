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
