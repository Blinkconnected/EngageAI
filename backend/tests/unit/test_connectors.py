"""The capability contract, and the flow derived from it.

The point of these tests is not that the arithmetic of ``steps_for`` is
right — it is short enough to read. It is that **the flow comes from
capabilities and never from a channel name**, because that is the property
which decides whether adding Slack next quarter is one file or a week of
touching every screen.

So the connectors here are fictional. If a test in this file ever needs to
know what WhatsApp is, the abstraction has stopped working.
"""

import pytest

from blinkengage.domain.connector import Attempt, Connector, DeploymentContext
from blinkengage.domain.connector_manifest import ConnectorCategory, ConnectorManifest
from blinkengage.domain.connectors import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    Capability,
    CapabilityState,
    CheckOutcome,
    ConnectorProfile,
    StepId,
    StepKind,
    blocks_connection,
    steps_for,
)

HOSTED = DeploymentContext(
    public_base_url="https://engage.example.com", configured_apps=frozenset({"acme"})
)
BARE = DeploymentContext(public_base_url="https://engage.example.com")


def profile(*capabilities: Capability, channel: str = "fictional") -> ConnectorProfile:
    return ConnectorProfile(
        channel_type=channel,
        declares=frozenset(capabilities),
        states=tuple(CapabilityState(c, available=True) for c in capabilities),
    )


class TestTheFlowComesFromCapabilities:
    def test_a_connector_that_can_only_be_typed_in_gets_a_form(self) -> None:
        """The Telegram shape, described without naming Telegram: one
        credential, no consent, nothing to enumerate."""
        steps = steps_for(profile(Capability.MANUAL_CONFIGURATION, Capability.HEALTH_CHECKS))

        assert [step.id for step in steps] == [
            StepId.SELECT,
            StepId.AUTHENTICATE,
            StepId.VERIFY,
            StepId.CONNECT,
        ]
        assert steps[1].kind is StepKind.FORM

    def test_a_connector_that_can_consent_gets_a_redirect(self) -> None:
        steps = steps_for(profile(Capability.OAUTH, Capability.MANUAL_CONFIGURATION))

        assert steps[1].kind is StepKind.OAUTH_REDIRECT

    def test_discovery_adds_a_picker(self) -> None:
        """The Meta shape: consent, then choose from what you own."""
        steps = steps_for(
            profile(
                Capability.OAUTH,
                Capability.AUTO_DISCOVERY,
                Capability.WEBHOOKS,
                Capability.HEALTH_CHECKS,
            )
        )

        assert [step.id for step in steps] == [
            StepId.SELECT,
            StepId.AUTHENTICATE,
            StepId.DISCOVER,
            StepId.VERIFY,
            StepId.CONNECT,
        ]
        assert steps[2].kind is StepKind.RESOURCE_PICKER

    def test_a_pasted_credential_skips_discovery_even_when_declared(self) -> None:
        """Discovery needs something to enumerate *with*. A customer who
        pasted one credential has already named the resource, and showing
        them a picker of one is a step that exists to be clicked past."""
        both = profile(
            Capability.OAUTH, Capability.AUTO_DISCOVERY, Capability.MANUAL_CONFIGURATION
        )

        via_oauth = steps_for(both, using_oauth=True)
        via_form = steps_for(both, using_oauth=False)

        assert StepId.DISCOVER in [step.id for step in via_oauth]
        assert StepId.DISCOVER not in [step.id for step in via_form]
        assert via_form[1].kind is StepKind.FORM

    def test_a_connector_with_nothing_to_check_gets_no_checklist(self) -> None:
        """A checklist of nothing is a step that only costs the customer a
        click, on the flow whose whole promise is two minutes."""
        steps = steps_for(profile(Capability.MANUAL_CONFIGURATION))

        assert StepId.VERIFY not in [step.id for step in steps]

    def test_every_flow_starts_by_choosing_and_ends_by_connecting(self) -> None:
        """The progress indicator has to mean the same thing everywhere, or
        a customer who connected one channel learns nothing for the next."""
        for capabilities in (
            (Capability.MANUAL_CONFIGURATION,),
            (Capability.OAUTH, Capability.AUTO_DISCOVERY),
            (Capability.WEBHOOKS,),
            (),
        ):
            steps = steps_for(profile(*capabilities))
            assert steps[0].id is StepId.SELECT, capabilities
            assert steps[-1].id is StepId.CONNECT, capabilities

    def test_the_console_only_ever_sees_six_renderers(self) -> None:
        """The rule that keeps `if channel == …` out of the frontend. A
        seventh renderer would be telling us something genuinely new about
        connecting to things — worth adding deliberately, not by accident."""
        every_flow = [
            steps_for(profile(*combination))
            for combination in (
                (),
                (Capability.MANUAL_CONFIGURATION,),
                (Capability.OAUTH,),
                (Capability.OAUTH, Capability.AUTO_DISCOVERY),
                (Capability.OAUTH, Capability.AUTO_DISCOVERY, Capability.HEALTH_CHECKS),
                (Capability.WEBHOOKS, Capability.MANUAL_CONFIGURATION),
            )
        ]

        kinds = {step.kind for flow in every_flow for step in flow}
        assert kinds <= set(StepKind)


class TestCapabilitiesResolvePerDeployment:
    """One connector, three rows in an operator's mental model."""

    class Fictional(Connector):
        channel_type = "fictional"
        app_key = "acme"

        MANIFEST = ConnectorManifest(
            channel_type="fictional",
            name_key="connect.fictional.name",
            description_key="connect.fictional.description",
            category=ConnectorCategory.OTHER,
            icon="fictional",
            capabilities=frozenset(
                {
                    Capability.OAUTH,
                    Capability.AUTO_DISCOVERY,
                    Capability.WEBHOOKS,
                    Capability.MANUAL_CONFIGURATION,
                    Capability.HEALTH_CHECKS,
                }
            ),
        )

        @property
        def manifest(self) -> ConnectorManifest:
            return self.MANIFEST

        async def connect(self, **_kwargs: object) -> tuple:  # type: ignore[override]
            return ()

    def test_with_an_app_configured_it_offers_consent(self) -> None:
        resolved = self.Fictional().resolve(HOSTED)

        assert resolved.supports(Capability.OAUTH)
        assert resolved.supports(Capability.AUTO_DISCOVERY)
        assert resolved.connectable

    def test_without_one_it_falls_back_rather_than_disappearing(self) -> None:
        """The failure that matters. An installation with no provider app
        must still be able to connect the channel by hand — anything else
        makes a self-hosted deployment strictly worse than the config page
        this replaces."""
        resolved = self.Fictional().resolve(BARE)

        assert not resolved.supports(Capability.OAUTH)
        assert not resolved.supports(Capability.AUTO_DISCOVERY)
        assert resolved.supports(Capability.MANUAL_CONFIGURATION)
        assert resolved.connectable

    def test_it_says_why_in_a_code_the_console_can_translate(self) -> None:
        """Prose from the server is prose that can never be Arabic."""
        resolved = self.Fictional().resolve(BARE)

        assert resolved.reason(Capability.OAUTH) == "platform_app_not_configured"
        assert " " not in (resolved.reason(Capability.OAUTH) or "")

    def test_the_flow_degrades_with_it(self) -> None:
        """Not a separate code path — the same derivation, fewer inputs."""
        hosted = steps_for(self.Fictional().resolve(HOSTED))
        bare = steps_for(self.Fictional().resolve(BARE))

        assert [s.kind for s in hosted][1] is StepKind.OAUTH_REDIRECT
        assert [s.kind for s in bare][1] is StepKind.FORM
        assert StepId.DISCOVER not in [s.id for s in bare]

    def test_capabilities_that_need_no_app_survive_without_one(self) -> None:
        resolved = self.Fictional().resolve(BARE)

        assert resolved.supports(Capability.WEBHOOKS)
        assert resolved.supports(Capability.HEALTH_CHECKS)


class TestAConnectorWithAlmostNothing:
    """The bar for adding a channel: three members and it works."""

    class Minimal(Connector):
        channel_type = "minimal"

        MANIFEST = ConnectorManifest(
            channel_type="minimal",
            name_key="connect.minimal.name",
            description_key="connect.minimal.description",
            category=ConnectorCategory.OTHER,
            icon="minimal",
            capabilities=frozenset({Capability.MANUAL_CONFIGURATION}),
        )

        @property
        def manifest(self) -> ConnectorManifest:
            return self.MANIFEST

        async def connect(self, **_kwargs: object) -> tuple:  # type: ignore[override]
            return ()

    def test_it_resolves_and_produces_a_flow(self) -> None:
        resolved = self.Minimal().resolve(BARE)

        assert resolved.connectable
        assert [s.id for s in steps_for(resolved)] == [
            StepId.SELECT,
            StepId.AUTHENTICATE,
            StepId.CONNECT,
        ]

    async def test_the_optional_halves_are_genuinely_optional(self) -> None:
        connector = self.Minimal()

        assert connector.credential_fields() == ()
        assert await connector.discover(grant={}) == ()
        assert await connector.validate(Attempt(context=BARE)) == ()

    async def test_what_it_cannot_do_it_refuses_by_name(self) -> None:
        """So a wizard bug surfaces as "minimal does not support OAuth"
        rather than as an empty redirect."""
        connector = self.Minimal()

        with pytest.raises(NotImplementedError, match="minimal"):
            await connector.authorize_url(state="s", context=BARE)


class TestAConnectorNobodyCanUse:
    def test_it_reports_itself_unconnectable(self) -> None:
        """Neither consent nor a form is a dead end, and offering it in the
        picker would be an invitation to one."""
        resolved = ConnectorProfile(
            channel_type="stub",
            declares=frozenset({Capability.WEBHOOKS}),
            states=(CapabilityState(Capability.WEBHOOKS, available=True),),
        )

        assert not resolved.connectable


class TestTheChecklist:
    def test_only_a_failure_blocks(self) -> None:
        """A warning that blocked would teach customers to click past the
        checklist, which is how the real failure gets missed."""
        assert not blocks_connection(
            (CheckOutcome("scopes", CHECK_OK), CheckOutcome("quality", CHECK_WARN))
        )
        assert blocks_connection(
            (CheckOutcome("scopes", CHECK_OK), CheckOutcome("messaging", CHECK_FAIL))
        )

    def test_nothing_to_report_does_not_block(self) -> None:
        assert not blocks_connection(())


class TestCapabilityStateIsHonest:
    def test_an_available_capability_cannot_carry_an_excuse(self) -> None:
        """Caught at construction, because a reason on an available
        capability is a contradiction the console would have to render."""
        with pytest.raises(ValueError, match="does not need a reason"):
            CapabilityState(Capability.OAUTH, available=True, reason="whatever")
