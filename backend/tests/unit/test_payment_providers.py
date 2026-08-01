"""Payment provider configuration.

Two things are pinned here, and both are the kind that fail quietly.

A **secret round-trip**: the console never receives a stored secret back, so a
form that submits what it was given submits nothing for that field. If absent
meant "cleared", opening the payment settings screen and pressing Save would
wipe every credential on the installation — with no error, and nothing visibly
wrong until the next customer tried to pay.

And **readiness**: a provider whose credentials are stored but whose adapter
does not exist must never present itself as something a customer can pay
through. A checkout button that cannot complete is worse than one that is
honestly absent.
"""

import pytest

from blinkengage.domain.payment_providers import (
    PAYMENT_PROVIDERS_KEY,
    PROVIDERS,
    PaymentFlow,
    ProviderConfig,
    ProviderReadiness,
    UnknownProviderKindError,
    apply,
    descriptor_for,
    from_stored,
    providers_for_country,
    to_stored,
)
from blinkengage.domain.payments import PaymentProviderKind


def a_config(kind: str = "paypal", **kw) -> ProviderConfig:
    defaults = {
        "kind": kind,
        "enabled": True,
        "values": {"client_id": "abc", "client_secret": "shhh"},
    }
    return ProviderConfig(**{**defaults, **kw})


class TestSecretsAreWriteOnly:
    def test_a_stored_secret_is_never_read_back(self) -> None:
        """The console shows *that* a secret is set, never what it is."""
        view = a_config().view()

        assert "client_secret" not in view.values
        assert view.values["client_id"] == "abc"

    def test_it_still_reports_which_secrets_exist(self) -> None:
        """The two facts together, from one call — and the reason ``view``
        exists rather than a redacted config.

        Stripping the secrets and *then* asking "is the password set?"
        answers no for every provider on the installation: the screen
        reports nothing configured while the credentials sit safely in the
        database. That was a real bug here, and the shape is the fix.
        """
        full = a_config().view()

        assert full.secret_set == {"client_secret": True}
        assert "client_secret" not in full.values
        assert a_config(values={"client_id": "abc"}).view().secret_set == {
            "client_secret": False
        }

    def test_saving_the_form_unchanged_does_not_erase_the_secret(self) -> None:
        """The one that matters. The console was never given the secret, so
        it submits ``None`` for it — and if that cleared the field, opening
        the screen and pressing Save would silently unconfigure payments."""
        stored = a_config()

        after = apply(stored, {"client_id": "abc", "client_secret": None})

        assert after.values["client_secret"] == "shhh"

    def test_an_empty_string_does_clear_it(self) -> None:
        """Clearing has to be possible, and unambiguous. Absent means
        unchanged; empty means gone."""
        after = apply(a_config(), {"client_secret": ""})

        assert after.values["client_secret"] == ""
        assert after.view().secret_set == {"client_secret": False}

    def test_a_secret_can_be_replaced(self) -> None:
        after = apply(a_config(), {"client_secret": "new"})

        assert after.values["client_secret"] == "new"

    def test_an_unknown_field_is_ignored_rather_than_rejected(self) -> None:
        """A console one release ahead of this build must still be able to
        save the fields that do exist."""
        after = apply(a_config(), {"client_id": "z", "field_from_the_future": 1})

        assert after.values["client_id"] == "z"
        assert "field_from_the_future" not in after.values


class TestReadinessIsHonest:
    def test_a_provider_with_no_adapter_says_so(self) -> None:
        """eFAWATEERcom credentials can be stored today; no bill is pushed.
        Reporting that as configured-and-working would put a payment route
        in front of a customer that silently goes nowhere."""
        config = ProviderConfig(
            kind="efawateercom",
            enabled=True,
            values={
                "biller_code": "123",
                "service_code": "1",
                "api_base_url": "https://x",
                "client_id": "a",
                "client_secret": "b",
            },
        )

        assert config.readiness() is ProviderReadiness.AWAITING_INTEGRATION

    def test_a_half_filled_provider_is_not_active(self) -> None:
        config = ProviderConfig(kind="paypal", enabled=True, values={"client_id": "abc"})

        assert config.missing_required() == ("client_secret",)
        assert config.readiness() is ProviderReadiness.NOT_CONFIGURED

    def test_a_complete_but_switched_off_provider_is_not_active(self) -> None:
        """Storing credentials and turning it on are two decisions."""
        assert a_config(enabled=False).readiness() is ProviderReadiness.NOT_CONFIGURED

    def test_a_complete_switched_on_provider_is_active(self) -> None:
        assert a_config().readiness() is ProviderReadiness.ACTIVE

    def test_manual_needs_no_configuration(self) -> None:
        """No configuration may be a precondition for recording money that
        has genuinely arrived."""
        manual = ProviderConfig(kind="manual", enabled=True)

        assert manual.missing_required() == ()
        assert manual.readiness() is ProviderReadiness.ACTIVE

    def test_an_optional_field_does_not_block_activation(self) -> None:
        assert "webhook_id" not in a_config().missing_required()


class TestEachSchemeIsModelledAsWhatItActuallyIs:
    def test_efawateercom_is_bill_presentment_not_a_redirect(self) -> None:
        """It publishes a bill that the customer pays at their own bank,
        on their own schedule. Modelling it as a checkout would produce a
        button leading somewhere the scheme does not have."""
        assert descriptor_for("efawateercom").flow is PaymentFlow.BILL_PRESENTMENT

    def test_cliq_is_a_credit_transfer_the_customer_initiates(self) -> None:
        """There is no merchant redirect: the customer pushes money to an
        alias quoting a reference. Nothing is started on our side, so there
        is no intent to expire."""
        assert descriptor_for("cliq").flow is PaymentFlow.CREDIT_TRANSFER

    def test_the_card_acquirers_are_redirects(self) -> None:
        assert descriptor_for("meps").flow is PaymentFlow.REDIRECT
        assert descriptor_for("network_international").flow is PaymentFlow.REDIRECT

    def test_manual_is_an_operator_recording_a_fact(self) -> None:
        assert descriptor_for("manual").flow is PaymentFlow.OPERATOR_ENTRY


class TestCountryScoping:
    def test_jordan_sees_the_jordanian_schemes(self) -> None:
        kinds = {p.kind.value for p in providers_for_country("JO")}

        assert {"efawateercom", "cliq", "meps"} <= kinds

    def test_germany_does_not(self) -> None:
        """A Jordanian bill reference shown to a customer in Germany is
        worse than showing nothing."""
        kinds = {p.kind.value for p in providers_for_country("DE")}

        assert "efawateercom" not in kinds
        assert "cliq" not in kinds
        assert "paypal" in kinds

    def test_manual_is_available_everywhere_including_nowhere(self) -> None:
        for country in ("JO", "DE", None):
            kinds = {p.kind.value for p in providers_for_country(country)}
            assert "manual" in kinds


class TestTheStoredShape:
    def test_a_provider_added_later_appears_on_an_older_installation(self) -> None:
        """An installation whose row predates a provider must show it
        immediately, not after somebody re-saves the form."""
        configs = from_stored({"paypal": {"enabled": True, "values": {}}})

        assert set(configs) == {p.kind.value for p in PROVIDERS}
        assert configs["meps"].enabled is False

    def test_nothing_stored_is_a_valid_installation(self) -> None:
        configs = from_stored(None)

        assert configs["paypal"].readiness() is ProviderReadiness.NOT_CONFIGURED

    def test_a_round_trip_preserves_everything(self) -> None:
        configs = from_stored(None)
        configs["paypal"] = a_config()

        assert from_stored(to_stored(configs))["paypal"] == a_config()

    def test_malformed_stored_values_do_not_raise(self) -> None:
        """Stored JSON is not typed. A settings row that a bad write left
        misshapen must not take the billing console down."""
        configs = from_stored({"paypal": {"enabled": True, "values": "not-a-dict"}})

        assert configs["paypal"].values == {}

    def test_the_settings_group_has_a_stable_key(self) -> None:
        assert PAYMENT_PROVIDERS_KEY == "payment_providers"


class TestTheDescriptorsAndTheEnumAgree:
    def test_every_descriptor_names_a_real_provider_kind(self) -> None:
        """A descriptor for a kind the enum lacks is a provider that can be
        configured and never recorded against a payment."""
        for descriptor in PROVIDERS:
            assert isinstance(descriptor.kind, PaymentProviderKind)

    def test_every_provider_kind_has_a_descriptor(self) -> None:
        """The other direction. A kind with no descriptor cannot be
        configured from the console, so it would be a payment route with
        no way to switch it on."""
        described = {p.kind for p in PROVIDERS}

        assert described == set(PaymentProviderKind)

    def test_a_provider_that_cannot_be_connected_explains_why(self) -> None:
        """"Awaiting integration" with no reason leaves an operator
        wondering whether they typed something wrong."""
        for descriptor in PROVIDERS:
            if not descriptor.has_adapter:
                assert descriptor.pending_note, descriptor.kind

    def test_an_unknown_kind_is_refused_clearly(self) -> None:
        with pytest.raises(UnknownProviderKindError):
            descriptor_for("some_gateway")
