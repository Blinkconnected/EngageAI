"""Public release/version metadata endpoints.

Deliberately unauthenticated — like ``health.py`` — so load balancers,
status pages, support tooling, and even unauthenticated customers/browsers
can discover which release is running without an API credential.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from blinkengage.api.deps import get_settings_dep
from blinkengage.core.changelog import (
    ChangelogFormatError,
    Release,
    ReleaseChannel,
    current_release,
    load_releases,
)
from blinkengage.core.config import Settings

router = APIRouter(tags=["version"])


def _load_releases_or_503(settings: Settings) -> list[Release]:
    """Read and parse ``settings.changelog_path``, translating the two
    ways this can fail at request time (the file disappearing/becoming
    unreadable, or its content being malformed) into a proper JSON error
    response instead of an unhandled exception.

    Neither ``ChangelogFormatError`` (a ``ValueError`` subclass, not a
    ``DomainError``) nor ``OSError``/``FileNotFoundError`` is caught by
    ``core.exceptions.register_exception_handlers`` — left unhandled they
    would otherwise surface as a bare, bodyless HTTP 500 on these
    deliberately-unauthenticated status endpoints. This is always an
    operator/deployment error (a corrupted or missing ``CHANGELOG.md``),
    never something the client can have caused, so it maps to 503 like
    ``AiNotConfiguredError``/``ErpNotConfiguredError`` in
    ``core/exceptions.py`` rather than 400/404/500.
    """
    return _load_from(Path(settings.changelog_path))


def _load_from(path: Path) -> list[Release]:
    try:
        return load_releases(path)
    except (ChangelogFormatError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unable to read release information: {exc}",
        ) from exc


class VersionResponse(BaseModel):
    product: str
    version: str
    build: str
    git_commit: str
    release_date: date | None
    release_channel: ReleaseChannel
    docker_image_tag: str


@router.get("/version", response_model=VersionResponse)
async def get_version(settings: Annotated[Settings, Depends(get_settings_dep)]) -> VersionResponse:
    """The currently running release's identity, for status pages, support
    tooling, and troubleshooting — the current release is the topmost
    entry (in file order) of ``settings.changelog_path``."""
    releases = _load_releases_or_503(settings)
    latest = current_release(releases)
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CHANGELOG.md has no published release entries",
        )
    return VersionResponse(
        product=settings.app_name,
        version=latest.version,
        build=settings.build_timestamp,
        git_commit=settings.git_commit,
        release_date=latest.release_date,
        release_channel=latest.channel,
        docker_image_tag=settings.docker_image_tag,
    )


@router.get("/releases", response_model=list[Release])
async def list_releases(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    lang: Annotated[
        Literal["en", "ar"],
        Query(description="Language for release notes. Untranslated entries fall back to English."),
    ] = "en",
) -> list[Release]:
    """The full parsed release history, excluding the ``Unreleased``
    entry — an "About" / "What's new" page's data source. Not paginated:
    changelog history is small and read infrequently, matching
    ``health.py``'s "keep it simple" bar.

    **English is the spine.** The English file decides which releases
    exist and in what order; a translation may only replace the prose of
    a release already there. It cannot add a release, remove one, or
    reorder them, so a translation that falls behind — or one somebody
    edits carelessly — degrades to English rather than misrepresenting
    the history.

    A missing or malformed translation file is not an error either: it
    logs nothing to the caller and the whole response is English. Release
    notes are the wrong thing to fail a request over.
    """
    english = _load_releases_or_503(settings)
    if lang == "en":
        return english

    try:
        translated = {
            release.version: release for release in _load_from(Path(settings.changelog_path_ar))
        }
    except HTTPException:
        return english

    return [translated.get(release.version, release) for release in english]
