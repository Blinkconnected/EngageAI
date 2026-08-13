"""The multi-worker metrics defect, reproduced and then held closed.

Production ran ``uvicorn --workers 4`` with ``prometheus_client`` in its
default single-process mode. Each worker counted its own traffic in its
own memory and ``/metrics`` was answered by whichever one the connection
reached, so eight consecutive scrapes of an idle backend returned
51, 40, 51, 40, 51, 12, 51, 51 for the same counter. Nothing errored;
the series simply moved backwards, which ``rate()`` interprets as a
counter reset.

These tests drive ``prometheus_client``'s multiprocess machinery the way
the library's own suite does — ``MultiProcessValue`` with a fixed pid per
simulated worker, writing the same mmap files four real workers would
write — so the aggregation, the stability across repeated scrapes and
the restart behaviour are exercised rather than described.

``test_the_old_expose_path_would_have_dropped_the_operational_collector``
is the regression this refactor was most at risk of introducing, and is
worth reading before changing anything here.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from prometheus_client import REGISTRY, Counter, values
from prometheus_client.values import MultiProcessValue

from blinkengage.core.metrics_exposition import (
    MULTIPROC_ENV_VAR,
    build_exposition_registry,
    multiprocess_dir,
    render_metrics,
    reset_multiprocess_dir,
)
from blinkengage.core.operational_metrics import OperationalCollector

COUNTER = "blinkengage_test_requests"


@pytest.fixture
def multiproc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Put ``prometheus_client`` into multiprocess mode against a temp dir.

    ``values.ValueClass`` is module-global and chosen at import time, so it
    is restored afterwards — leaving it swapped would put every later test
    in the session into multiprocess mode against a deleted directory.
    """
    monkeypatch.setenv(MULTIPROC_ENV_VAR, str(tmp_path))
    original = values.ValueClass
    try:
        yield tmp_path
    finally:
        values.ValueClass = original


def _worker(pid: int, name: str = COUNTER, labelnames: Sequence[str] = ()) -> Counter:
    """A counter as it would be created inside worker process ``pid``.

    ``registry=None`` keeps these out of the global registry; in
    multiprocess mode the samples go to the pid-keyed file either way,
    which is the whole point.
    """
    values.ValueClass = MultiProcessValue(lambda: pid)
    return Counter(name, "Test counter.", labelnames=list(labelnames), registry=None)


def _sample(name: str = f"{COUNTER}_total", **labels: str) -> float | None:
    """Read one sample through a freshly built exposition registry.

    Rebuilt per call on purpose: that is what a real scrape does, so a
    caching mistake in ``build_exposition_registry`` shows up here.
    """
    return build_exposition_registry().get_sample_value(name, labels or None)


# --- aggregation across workers ---------------------------------------


def test_counters_from_every_worker_are_summed(multiproc: Path) -> None:
    # The production reading, exactly: three workers that had each served
    # a different amount of traffic.
    _worker(101).inc(51)
    _worker(102).inc(40)
    _worker(103).inc(12)

    assert _sample() == 103


def test_repeated_scrapes_are_stable_without_new_traffic(multiproc: Path) -> None:
    _worker(201).inc(51)
    _worker(202).inc(40)
    _worker(203).inc(12)

    readings = [_sample() for _ in range(8)]

    # The defect produced eight readings and three distinct values.
    assert readings == [103.0] * 8


def test_aggregate_grows_by_exactly_the_traffic_served(multiproc: Path) -> None:
    first, second = _worker(301), _worker(302)
    for _ in range(60):
        first.inc()
    for _ in range(40):
        second.inc()
    assert _sample() == 100

    # A second known burst, split unevenly across the same workers.
    for _ in range(17):
        first.inc()
    for _ in range(8):
        second.inc()

    assert _sample() == 125


def test_labels_are_aggregated_per_series_not_collapsed(multiproc: Path) -> None:
    labels = ("method", "status", "handler")
    first = _worker(401, labelnames=labels)
    second = _worker(402, labelnames=labels)

    first.labels("GET", "2xx", "/api/v1/conversations").inc(3)
    second.labels("GET", "2xx", "/api/v1/conversations").inc(4)
    second.labels("POST", "5xx", "/api/v1/auth/login").inc(1)
    first.labels("GET", "4xx", "/api/v1/conversations").inc(2)

    ok = {"method": "GET", "status": "2xx", "handler": "/api/v1/conversations"}
    bad = {"method": "POST", "status": "5xx", "handler": "/api/v1/auth/login"}
    client_error = {"method": "GET", "status": "4xx", "handler": "/api/v1/conversations"}

    assert _sample(**ok) == 7
    assert _sample(**bad) == 1
    assert _sample(**client_error) == 2


def test_a_5xx_on_one_worker_is_visible_to_every_scrape(multiproc: Path) -> None:
    """The failure that made the alert unable to see real errors.

    Worker 502 records the only 5xx. Under the old arrangement a scrape
    answered by 501 saw no such series at all, so the alert's numerator
    was empty and it reported no data instead of an error rate.
    """
    labels = ("status",)
    _worker(501, labelnames=labels).labels("2xx").inc(99)
    _worker(502, labelnames=labels).labels("5xx").inc(1)

    assert _sample(status="5xx") == 1
    assert _sample(status="2xx") == 99


# --- directory lifecycle ----------------------------------------------


def test_reset_removes_stale_sample_files(tmp_path: Path) -> None:
    (tmp_path / "counter_101.db").write_bytes(b"stale")
    (tmp_path / "histogram_102.db").write_bytes(b"stale")
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("not ours")

    reset_multiprocess_dir(tmp_path)

    assert list(tmp_path.glob("*.db")) == []
    assert unrelated.exists(), "only prometheus sample files should be removed"


def test_reset_creates_the_directory_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "prometheus"

    reset_multiprocess_dir(target)

    assert target.is_dir()


def test_counters_do_not_survive_a_container_restart(multiproc: Path) -> None:
    """Stale files are read as live workers, so they must not persist.

    pids are recycled. A file left by the previous run is indistinguishable
    from a running worker's, so without the reset the counter resurrects
    and any rate spanning the restart is fabricated.
    """
    _worker(601).inc(51)
    assert _sample() == 51

    reset_multiprocess_dir(multiproc)

    assert _sample() is None


# --- registry composition ---------------------------------------------


def test_operational_collector_is_served_in_multiprocess_mode(multiproc: Path) -> None:
    collector = OperationalCollector(expected_intervals={"blinkengage.tasks.sweep": 60.0})

    payload = render_metrics(collector).decode()

    assert "blinkengage_scheduler_expected_interval_seconds" in payload


def test_the_old_expose_path_would_have_dropped_the_operational_collector(
    multiproc: Path,
) -> None:
    """Why ``/metrics`` is mounted by hand instead of by ``.expose()``.

    In multiprocess mode the exposition registry is built fresh and holds
    only the workers' file-backed samples. ``Instrumentator.expose()``
    builds exactly this registry and has no way to be told about a
    collector that lives in memory — so the outbox and scheduler gauges
    would have disappeared and the two alerts reading them would have
    found no series, which reads as healthy.
    """
    collector = OperationalCollector(expected_intervals={"blinkengage.tasks.sweep": 60.0})
    _worker(701).inc(1)

    without_collector = render_metrics().decode()

    assert "blinkengage_scheduler_expected_interval_seconds" not in without_collector
    assert f"{COUNTER}_total" in without_collector
    assert "blinkengage_scheduler_expected_interval_seconds" in render_metrics(collector).decode()


# --- single-process behaviour is untouched ----------------------------


def test_single_process_mode_serves_the_default_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MULTIPROC_ENV_VAR, raising=False)

    assert multiprocess_dir() is None
    assert build_exposition_registry() is REGISTRY


def test_blank_environment_variable_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty value is a deployment mistake, not a reason to fail to boot.

    ``prometheus_client`` raises on an empty path; degrading to
    single-process keeps the container serving.
    """
    monkeypatch.setenv(MULTIPROC_ENV_VAR, "")

    assert multiprocess_dir() is None
    assert build_exposition_registry() is REGISTRY
