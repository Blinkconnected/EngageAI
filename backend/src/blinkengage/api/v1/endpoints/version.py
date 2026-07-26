"""Public release/version metadata endpoints.

Deliberately unauthenticated — like ``health.py`` — so load balancers,
status pages, support tooling, and even unauthenticated customers/browsers
can discover which release is running without an API credential.
"""

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
    try:
        return load_releases(Path(settings.changelog_path))
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
async def list_releases(settings: Annotated[Settings, Depends(get_settings_dep)]) -> list[Release]:
    """The full parsed release history from ``settings.changelog_path``,
    excluding the ``Unreleased`` entry — an "About" / "What's new" page's
    data source. Not paginated: changelog history is small and read
    infrequently, matching ``health.py``'s "keep it simple" bar."""
    return _load_releases_or_503(settings)
