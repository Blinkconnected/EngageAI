"""Tripwire: the three places a released version number lives must agree.

Reads the REAL repository files directly (not a test fixture) so this
fails the moment any one of them drifts from the others:

- ``/CHANGELOG.md``'s topmost published release (parsed the same way the
  running application parses it, via ``core.changelog``).
- ``backend/pyproject.toml``'s ``[project].version``.
- ``frontend/package.json``'s ``"version"``.

Path resolution has to account for two different filesystem layouts this
suite runs under:

- On a bare host checkout, ``backend/tests/unit/`` sits three levels below
  the actual repo root, where ``CHANGELOG.md`` and ``frontend/`` live
  alongside ``backend/``.
- Inside the ``backend`` container (``docker compose exec backend
  pytest ...``), only ``./backend`` is bind-mounted, flattened directly
  onto ``/app`` — there is no accessible parent directory representing the
  real repo root. ``CHANGELOG.md`` and ``frontend/package.json`` are
  therefore bind-mounted individually (see ``docker-compose.yml``'s
  ``backend`` service) at container-specific paths instead.
"""

import json
import tomllib
from pathlib import Path

from blinkengage.core.changelog import current_release, load_releases

# backend/tests/unit/test_version_consistency.py -> backend/tests/unit ->
# backend/tests -> backend. This level is identical on the host checkout
# and inside the container (where /app *is* the backend root), unlike the
# repo root above it, whose layout differs between the two (see module
# docstring).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Host checkout: repo_root/CHANGELOG.md, one level above backend/.
# Container: bind-mounted directly at backend_root/CHANGELOG.md (see
# docker-compose.yml).
_CHANGELOG_CANDIDATES = (
    _BACKEND_ROOT.parent / "CHANGELOG.md",
    _BACKEND_ROOT / "CHANGELOG.md",
)

# Host checkout: repo_root/frontend/package.json.
# Container: bind-mounted directly at /frontend/package.json (see
# docker-compose.yml) since frontend/ is otherwise invisible to the
# backend container entirely.
_PACKAGE_JSON_CANDIDATES = (
    _BACKEND_ROOT.parent / "frontend" / "package.json",
    Path("/frontend/package.json"),
)


def _resolve(candidates: tuple[Path, ...], description: str) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not locate {description}; tried: {[str(c) for c in candidates]}"
    )


def _changelog_version() -> str:
    changelog_path = _resolve(_CHANGELOG_CANDIDATES, "the repo-root CHANGELOG.md")
    releases = load_releases(changelog_path)
    latest = current_release(releases)
    assert latest is not None, "CHANGELOG.md has no published release entries"
    return latest.version


def _backend_version() -> str:
    # Always directly inside the backend root in both layouts.
    pyproject_path = _BACKEND_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)
    return str(data["project"]["version"])


def _frontend_version() -> str:
    package_json_path = _resolve(_PACKAGE_JSON_CANDIDATES, "frontend/package.json")
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    return str(data["version"])


def test_changelog_pyproject_and_package_json_versions_match() -> None:
    changelog_version = _changelog_version()
    backend_version = _backend_version()
    frontend_version = _frontend_version()

    # Raw string comparison — `packaging` is not a dependency of this
    # project, and these three fields are hand-authored in lockstep by
    # release procedure (see docs/architecture/release-changelog.md)
    # rather than independently formatted, so no normalization is needed.
    assert changelog_version == backend_version, (
        f"CHANGELOG.md's current release ({changelog_version!r}) does not match "
        f"backend/pyproject.toml's [project].version ({backend_version!r})"
    )
    assert changelog_version == frontend_version, (
        f"CHANGELOG.md's current release ({changelog_version!r}) does not match "
        f"frontend/package.json's version ({frontend_version!r})"
    )
