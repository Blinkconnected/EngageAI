"""Integration tests for the public, unauthenticated version/release API.

Exercises the ``tests/fixtures/CHANGELOG.md`` fixture (wired in via the
``CHANGELOG_PATH`` env override in ``pyproject.toml``'s ``[tool.pytest.ini_options]``),
not the real repo-root ``CHANGELOG.md`` — see ``test_version_consistency.py``
for the test that checks the real repo files instead.

Note on the fixture's topmost entry: per ``tests/fixtures/CHANGELOG.md``,
the stable ``2.0.0`` release sits above the ``2.0.0-beta.1`` release (a
later stable release listed above an earlier beta with the same SemVer
core — the same "most recent release first" convention the real
``/CHANGELOG.md`` and ``core.changelog``'s own parser tests use), so
``current_release()`` — and therefore ``GET /api/v1/version`` — reports
the *stable* release, not the beta one.
"""

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from blinkengage.api.deps import get_settings_dep


async def test_version_endpoint_requires_no_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "Blink Engage"
    assert body["version"] == "2.0.0"
    assert body["release_channel"] == "stable"
    assert body["release_date"] == "2026-01-01"
    # Settings' plain defaults — no CI/build-pipeline env override is set
    # for these fields in the test environment.
    assert body["git_commit"] == "unknown"
    assert body["build"] == "unknown"
    assert body["docker_image_tag"] == "development"


async def test_releases_endpoint_requires_no_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/releases")

    assert response.status_code == 200
    body = response.json()

    # Exactly the fixture's 2 non-Unreleased entries, in file order —
    # "Unreleased" itself must never be surfaced by this endpoint.
    assert [release["version"] for release in body] == ["2.0.0", "2.0.0-beta.1"]

    stable, beta = body
    assert stable["release_date"] == "2026-01-01"
    assert stable["channel"] == "stable"
    assert stable["added"] == ["Widget dashboard", "CSV export"]
    assert stable["improved"] == ["Faster search indexing"]
    assert stable["fixed"] == ["Fixed pagination off-by-one on the queue list"]
    assert stable["known_issues"] == ["Search results are capped at 500 rows"]
    assert stable["security"] == []
    assert stable["breaking_changes"] == []
    assert stable["deprecated"] == []

    assert beta["release_date"] == "2025-12-01"
    assert beta["channel"] == "beta"
    assert beta["security"] == ["Hardened session cookie flags"]
    assert beta["breaking_changes"] == ["Renamed `legacy_id` field to `external_id`"]
    assert beta["deprecated"] == ["Legacy `/v0/widgets` endpoint"]
    assert beta["added"] == []
    assert beta["improved"] == []
    assert beta["fixed"] == []
    assert beta["known_issues"] == []


async def test_openapi_schema_reports_the_fixture_current_release_version(
    client: AsyncClient,
) -> None:
    # Proves the main.py fix end-to-end: the FastAPI app's own advertised
    # `info.version` (previously hardcoded to "0.1.0") is now derived from
    # the same changelog the version API reads.
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["version"] == "2.0.0"


def _override_changelog_path(app: Any, changelog_path: Path) -> None:
    settings = app.state.container.settings()
    app.dependency_overrides[get_settings_dep] = lambda: settings.model_copy(
        update={"changelog_path": str(changelog_path)}
    )


async def test_version_endpoint_returns_503_with_detail_when_changelog_has_no_releases(
    app: Any, client: AsyncClient, tmp_path: Path
) -> None:
    """ChangelogFormatError must never surface as a bare, bodyless HTTP 500
    on this deliberately-unauthenticated endpoint — it is translated to a
    503 carrying the crafted, informative detail message."""
    broken_changelog = tmp_path / "CHANGELOG.md"
    broken_changelog.write_text("## [Unreleased]\n", encoding="utf-8")
    _override_changelog_path(app, broken_changelog)

    try:
        response = await client.get("/api/v1/version")
    finally:
        del app.dependency_overrides[get_settings_dep]

    assert response.status_code == 503
    assert response.json()["detail"] == "CHANGELOG.md has no published release entries"


async def test_version_endpoint_returns_503_when_changelog_file_is_missing(
    app: Any, client: AsyncClient, tmp_path: Path
) -> None:
    """A ``FileNotFoundError`` at request time (file deleted/moved after
    startup, or ``CHANGELOG_PATH`` repointed) must also be translated,
    not left to bubble up as an unhandled exception."""
    _override_changelog_path(app, tmp_path / "does-not-exist.md")

    try:
        response = await client.get("/api/v1/version")
    finally:
        del app.dependency_overrides[get_settings_dep]

    assert response.status_code == 503
    assert "Unable to read release information" in response.json()["detail"]


async def test_releases_endpoint_returns_503_with_detail_on_malformed_changelog(
    app: Any, client: AsyncClient, tmp_path: Path
) -> None:
    broken_changelog = tmp_path / "CHANGELOG.md"
    broken_changelog.write_text("## Random prose without brackets\n", encoding="utf-8")
    _override_changelog_path(app, broken_changelog)

    try:
        response = await client.get("/api/v1/releases")
    finally:
        del app.dependency_overrides[get_settings_dep]

    assert response.status_code == 503
    assert "Malformed release heading" in response.json()["detail"]
