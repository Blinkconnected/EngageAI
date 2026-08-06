"""Building the app twice in one process must not raise.

``prometheus_client`` refuses to register two collectors exporting the
same metric name, and the test suite constructs the application many
times in a single process. So registration has to be idempotent — and
*how* it is made idempotent turns out to matter.

The first attempt keyed on a metric name, which looked correct and was
not: ``prometheus_client`` learns a collector's names by calling
``collect()`` at registration time, and this collector emits nothing
until its first refresh. Whether the guard's chosen name had been
recorded therefore depended on what the collector happened to be holding
at that moment. Adding a gauge that *is* populated at construction
changed which names got recorded, the guard stopped matching, and every
integration test after the first errored with "Duplicated timeseries".

A unit test is the right home for this: the failure needs two app
constructions in one process, which is exactly what a test session does
and what a production process never does.
"""

from prometheus_client import CollectorRegistry

from blinkengage.core.operational_metrics import OperationalCollector, register


def _operational_collectors(registry: CollectorRegistry) -> int:
    collectors = getattr(registry, "_collector_to_names", {})
    return sum(isinstance(collector, OperationalCollector) for collector in collectors)


def test_registering_twice_is_a_no_op() -> None:
    registry = CollectorRegistry()

    register(registry, OperationalCollector())
    register(registry, OperationalCollector())  # would raise if unguarded

    assert _operational_collectors(registry) == 1


def test_the_guard_holds_when_the_collector_has_metrics_to_emit() -> None:
    """The case the name-based guard got wrong.

    A collector constructed with intervals emits a gauge on its very
    first ``collect()``, so the registry records a different set of names
    than an empty one does. The guard must not depend on which.
    """
    registry = CollectorRegistry()

    register(registry, OperationalCollector(expected_intervals={"a.task": 60.0}))
    register(registry, OperationalCollector(expected_intervals={"a.task": 60.0}))

    assert _operational_collectors(registry) == 1


def test_a_registered_collector_still_exports_its_metrics() -> None:
    # The guard must not be so eager that it swallows the *first*
    # registration too. A silent no-op there would mean no metrics at all,
    # and the alerts built on them would go quiet without anything failing.
    registry = CollectorRegistry()
    register(registry, OperationalCollector(expected_intervals={"a.task": 60.0}))

    names = {metric.name for metric in registry.collect()}
    assert "blinkengage_scheduler_expected_interval_seconds" in names
