"""The billable-metric catalog.

The rule this pins: **metrics are code, pricing is data**. A metric may
only exist if the platform can actually measure it, so these tests are
mostly about what the catalog *refuses* to allow.
"""

from blinkengage.domain.billable_metrics import (
    METRIC_CODES,
    METRICS,
    MeasurementUnit,
    MetricAvailability,
    get_metric,
    is_known_metric,
    is_priceable,
    is_retired,
    priceable_metrics,
    retired_metrics,
)


class TestCatalogShape:
    def test_the_billable_message_is_the_metric_that_bills(self) -> None:
        metric = get_metric("BILLABLE_MESSAGE")

        assert metric is not None
        assert metric.unit is MeasurementUnit.MESSAGE
        assert metric.is_priceable

    def test_it_is_the_only_priceable_metric(self) -> None:
        """One charge per customer-facing message, and nothing else metered.
        A second priceable metric would mean a surcharge, which is exactly
        what this model replaced."""
        assert [metric.code for metric in priceable_metrics()] == ["BILLABLE_MESSAGE"]

    def test_every_metric_exposes_the_metadata_the_admin_ui_needs(self) -> None:
        for metric in METRICS:
            assert metric.code
            assert metric.display_name
            assert metric.description
            assert isinstance(metric.unit, MeasurementUnit)

    def test_codes_are_unique(self) -> None:
        assert len(METRIC_CODES) == len(METRICS)

    def test_codes_are_stable_public_identifiers(self) -> None:
        """Codes appear in pricing rows, usage records and invoices, so
        renaming one silently reprices history. This is a tripwire, not
        a style check — if it fails, something was renamed rather than
        added."""
        assert {metric.code for metric in METRICS} == {
            "BILLABLE_MESSAGE",
            # Retired, and still here. These codes are on issued invoices,
            # closed period snapshots and pricing history; deleting one would
            # make a historical document unreadable.
            "CONVERSATION",
            "AI_ASSISTED_REPLY",
            "AI_AUTOPILOT",
            "VOICE_MINUTE",
            "STORAGE_GB",
        }

    def test_units_are_not_all_the_same(self) -> None:
        """A per-conversation count exercises none of the hard cases. The
        catalog deliberately carries a fractional unit (minutes) and a
        sampled-rate unit (GB-month) so the pricing schema is designed
        against the real shape of the problem."""
        units = {metric.unit for metric in METRICS}

        assert MeasurementUnit.MINUTE in units
        assert MeasurementUnit.GIGABYTE_MONTH in units


class TestMeasurabilityGate:
    def test_a_metric_with_no_meter_cannot_be_priced(self) -> None:
        """The guarantee: every billable metric has a measurement engine.
        Voice and storage are declared but nothing measures them yet, so
        an operator must not be able to attach a rate — they would see no
        charges and reasonably conclude billing is broken."""
        assert is_known_metric("VOICE_MINUTE")
        assert not is_priceable("VOICE_MINUTE")

        assert is_known_metric("STORAGE_GB")
        assert not is_priceable("STORAGE_GB")

    def test_measured_metrics_are_priceable(self) -> None:
        assert is_priceable("BILLABLE_MESSAGE")

    def test_a_retired_metric_is_known_but_not_priceable(self) -> None:
        """The point of retirement: no new rate may be set, and everything
        already recorded still reads. A closed period priced per conversation
        must keep pricing that way — deleting the metric would make its
        invoice unreprintable."""
        for code in ("CONVERSATION", "AI_ASSISTED_REPLY", "AI_AUTOPILOT"):
            assert is_known_metric(code), code
            assert is_retired(code), code
            assert not is_priceable(code), code

    def test_retired_metrics_are_listed_for_a_console(self) -> None:
        """So a company's historical charges show a label rather than a bare
        code somebody has to look up."""
        assert {metric.code for metric in retired_metrics()} == {
            "CONVERSATION",
            "AI_ASSISTED_REPLY",
            "AI_AUTOPILOT",
        }

    def test_priceable_metrics_excludes_planned_ones(self) -> None:
        assert all(m.availability is MetricAvailability.MEASURED for m in priceable_metrics())
        assert len(priceable_metrics()) < len(METRICS)

    def test_an_unknown_metric_is_neither_known_nor_priceable(self) -> None:
        """Administrators cannot invent metrics. An unrecognised code is
        rejected rather than quietly accepted and stored — a typo that
        persists looks like a working price that charges nobody."""
        assert not is_known_metric("TELEPATHY")
        assert not is_priceable("TELEPATHY")
        assert get_metric("TELEPATHY") is None


def test_the_catalog_is_immutable_at_runtime() -> None:
    """Metrics are part of the application, not configuration. A tuple of
    frozen dataclasses means nothing can append to or mutate the catalog
    at runtime, which is what "adding a metric requires a release"
    actually means in code."""
    import dataclasses

    import pytest

    assert isinstance(METRICS, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        METRICS[0].code = "SOMETHING_ELSE"  # type: ignore[misc]
