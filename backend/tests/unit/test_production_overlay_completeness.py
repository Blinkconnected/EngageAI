"""Every production service is bounded, restarted, probed and rotated.

Three services were missing from the production overlay entirely — one of
them on the billing path — so they ran with no memory limit and no
restart policy. A container with no limit does not fail politely: it
takes the host's memory, and the first thing to notice is the database
dying next to it.

The monitoring stack had the same gap for a different reason. It was
never in the overlay at all, so Prometheus and Loki — both of which grow
with retention — ran unbounded on the services whose entire job is to
tell you the host is in trouble.

The failure mode this guards is not "somebody wrote the wrong limit". It
is "somebody added a service and did not think about the overlay",
which is invisible until production runs out of something.

Parsed from the compose files directly rather than from `docker compose
config`, so the test needs no Docker daemon and runs in CI.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = REPO_ROOT / "docker-compose.yml"
PROD = REPO_ROOT / "docker-compose.prod.yml"

#: Runs once and exits. A restart policy would loop it and a healthcheck
#: has nothing to probe — but it still needs a memory limit and log
#: rotation, so it is exempted from two checks rather than all four.
ONE_SHOT = {"minio-init"}

#: Deliberately not run in production. Scaled to zero in the overlay
#: because Compose cannot delete an inherited service.
NOT_IN_PRODUCTION = {"greenmail"}


class _ComposeLoader(yaml.SafeLoader):
    """A loader that tolerates Compose's own YAML tags.

    The overlay uses ``!override`` to replace an inherited list rather
    than append to it. PyYAML refuses to construct an unknown tag, so
    without this the whole file fails to parse and the guard would be
    quietly skipped — which is the failure this test exists to prevent.
    """


def _drop_tag(loader: yaml.Loader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_constructor("!override", _drop_tag)
_ComposeLoader.add_constructor("!reset", _drop_tag)


def _merged() -> dict[str, dict]:
    """Base services with the overlay applied, shallowly.

    Shallow is enough: every property under test is set at the top level
    of a service, and a deep merge would only add ways for this to
    disagree with Compose about something that does not matter here.
    """
    base = yaml.load(BASE.read_text(), Loader=_ComposeLoader)["services"]
    overlay = yaml.load(PROD.read_text(), Loader=_ComposeLoader)["services"]
    merged = {name: dict(spec) for name, spec in base.items()}
    for name, spec in overlay.items():
        merged.setdefault(name, {}).update(spec)
    return merged


def _production_services() -> dict[str, dict]:
    return {
        name: spec
        for name, spec in _merged().items()
        if name not in NOT_IN_PRODUCTION
        # Scaled to zero, or held behind a profile that the production
        # command line does not activate. Both are ways of saying "this
        # does not run here" — `frontend` uses the second, because the
        # prod nginx image serves the compiled SPA instead.
        and spec.get("deploy", {}).get("replicas") != 0
        and not spec.get("profiles")
    }


@pytest.mark.parametrize("name", sorted(_production_services()))
def test_service_has_a_memory_limit(name: str) -> None:
    spec = _production_services()[name]
    limit = spec.get("deploy", {}).get("resources", {}).get("limits", {}).get("memory")
    assert limit, (
        f"'{name}' runs in production with no memory limit. One unbounded "
        "container is enough to take the host, and the database with it."
    )


@pytest.mark.parametrize("name", sorted(_production_services()))
def test_service_has_log_rotation(name: str) -> None:
    spec = _production_services()[name]
    assert spec.get("logging"), (
        f"'{name}' has no logging configuration, so the json-file driver "
        "grows without limit until the disk fills."
    )


@pytest.mark.parametrize("name", sorted(n for n in _production_services() if n not in ONE_SHOT))
def test_service_restarts_on_failure(name: str) -> None:
    spec = _production_services()[name]
    assert spec.get("restart") in {"always", "unless-stopped"}, (
        f"'{name}' has restart policy {spec.get('restart')!r} — a crash "
        "would leave it down until somebody noticed."
    )


@pytest.mark.parametrize("name", sorted(n for n in _production_services() if n not in ONE_SHOT))
def test_service_has_a_healthcheck(name: str) -> None:
    spec = _production_services()[name]
    healthcheck = spec.get("healthcheck") or {}
    assert healthcheck and not healthcheck.get("disable"), (
        f"'{name}' has no healthcheck, so a process that dies without " "exiting reads as running."
    )
