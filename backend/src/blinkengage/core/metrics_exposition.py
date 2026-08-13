"""One aggregated metrics view across every Uvicorn worker.

``prometheus_client`` keeps counters in process memory. That is correct
for one process and silently wrong for four: ``uvicorn --workers 4``
serves ``/metrics`` from whichever worker the connection lands on, so a
scrape returns that worker's slice of the traffic and nothing else. The
symptom is not an error — it is a counter that appears to *decrease*
between scrapes as different workers answer, which ``rate()`` reads as a
counter reset and compensates for by adding the whole value again. Every
rate built on those series is then wrong in both directions at once, and
a ``5xx`` recorded on worker 2 is invisible to a scrape answered by
worker 3.

The library's answer is multiprocess mode: each process writes its
samples to memory-mapped files in a shared directory, and exposition sums
them. Two things that mode needs, which setting the environment variable
alone does not give:

- **The directory must be emptied before the workers start.** The files
  are keyed by pid, and pids are recycled. Files left behind by a
  previous container run are read as live workers, so counters resurrect
  across restarts and a rate computed over the restart is fiction.
  Emptying it must happen once, in the parent, *before* any worker
  exists — a worker doing it at import time would delete its siblings'
  files. :func:`main` is that step, run from the entrypoint.
- **The exposition registry has to be assembled by hand.** In
  multiprocess mode the default ``REGISTRY`` is not what should be
  served: it holds only the calling worker's view. A fresh registry gets
  a :class:`~prometheus_client.multiprocess.MultiProcessCollector` for
  everything the workers recorded — but a collector registered on
  ``REGISTRY`` is then *not in it*. That is how
  :class:`~blinkengage.core.operational_metrics.OperationalCollector`
  would have vanished from ``/metrics``, taking the outbox-stalled and
  scheduler-stale alerts with it: both would have found no series and
  reported no data, which reads as healthy. It is added explicitly
  below.

The operational collector stays per-worker on purpose. It reports two
values read from the database — outbox depth and last scheduler run —
so every worker computes the same answer, and the serving worker's copy
is the right one to publish. Summing four identical copies is what would
be wrong.

Nothing here changes single-process behaviour: with the variable unset,
exposition serves the default registry exactly as before, which is what
the test suite and the ``--reload`` dev image run.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest
from prometheus_client import multiprocess as prometheus_multiprocess
from starlette.responses import Response

from blinkengage.core.operational_metrics import OperationalCollector

#: Read by ``prometheus_client`` itself, not only by this module — the
#: library switches every metric to file-backed storage when it is set, so
#: it has to be present in the environment of the *workers*, not merely
#: known here.
MULTIPROC_ENV_VAR = "PROMETHEUS_MULTIPROC_DIR"


def multiprocess_dir() -> str | None:
    """The configured multiprocess directory, or ``None`` when disabled.

    An empty string is treated as unset. ``prometheus_client`` raises on
    one, and an env var that exists but is blank is a deployment mistake
    that should degrade to single-process behaviour rather than refuse to
    boot.
    """
    return os.environ.get(MULTIPROC_ENV_VAR) or None


def reset_multiprocess_dir(path: str | Path) -> None:
    """Create the directory and remove any sample files already in it.

    Call exactly once per container start, from the parent process,
    before the workers are spawned. Removing only ``*.db`` leaves an
    operator's own files alone and keeps the call safe against a
    misconfigured path pointing somewhere shared.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.db"):
        stale.unlink(missing_ok=True)


def build_exposition_registry(
    collector: OperationalCollector | None = None,
) -> CollectorRegistry:
    """The registry ``/metrics`` should serve.

    Single-process: the default registry, which already holds everything.
    Multiprocess: a fresh registry holding the summed worker samples plus
    the operational collector, which lives in memory and would otherwise
    not be exposed at all.
    """
    directory = multiprocess_dir()
    if directory is None:
        return REGISTRY

    registry = CollectorRegistry()
    # prometheus_client ships py.typed but leaves this constructor
    # unannotated, so --strict rejects the call rather than the usage.
    prometheus_multiprocess.MultiProcessCollector(registry, path=directory)  # type: ignore[no-untyped-call]
    if collector is not None:
        registry.register(collector)
    return registry


def render_metrics(collector: OperationalCollector | None = None) -> bytes:
    """The exposition payload, in the Prometheus text format."""
    return generate_latest(build_exposition_registry(collector))


def expose_metrics(
    app: FastAPI,
    collector: OperationalCollector | None = None,
    endpoint: str = "/metrics",
) -> None:
    """Mount ``/metrics``.

    Replaces ``Instrumentator.expose()``, which builds its multiprocess
    registry internally and therefore cannot be told about a collector
    that is not file-backed. Instrumentation itself is unchanged and
    still comes from the instrumentator middleware.

    The registry is rebuilt per scrape rather than cached, matching the
    library's own behaviour: the set of live worker files changes when
    workers restart, and a registry built once at startup would keep
    reporting the shape it saw then.
    """

    def metrics() -> Response:
        return Response(content=render_metrics(collector), media_type=CONTENT_TYPE_LATEST)

    app.get(endpoint, include_in_schema=False)(metrics)


def main() -> None:
    """Entrypoint step: prepare the directory before the workers start."""
    directory = multiprocess_dir()
    if directory is None:
        return
    reset_multiprocess_dir(directory)


if __name__ == "__main__":  # pragma: no cover - exercised by the container entrypoint
    main()


__all__ = [
    "MULTIPROC_ENV_VAR",
    "build_exposition_registry",
    "expose_metrics",
    "main",
    "multiprocess_dir",
    "render_metrics",
    "reset_multiprocess_dir",
]
