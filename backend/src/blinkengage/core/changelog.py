"""Parser for the repository's ``CHANGELOG.md`` (Keep a Changelog format).

This module turns the free-text ``CHANGELOG.md`` into structured
:class:`Release` objects so other parts of the platform (e.g. an
"About" / "What's new" endpoint) can surface release information without
re-parsing Markdown themselves.

The parser is a small line-by-line state machine — not a single regex —
because the shape it accepts (a version heading, optional free-text
summary, then a sequence of ``### `` subsections each containing ``- ``
bullets) is inherently stateful. Any deviation from the expected shape
raises :class:`ChangelogFormatError` naming the offending heading/version
so a malformed changelog entry fails loudly at parse time rather than
silently producing incomplete data.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

ReleaseChannel = Literal["development", "beta", "release-candidate", "stable"]


class Release(BaseModel):
    """A single parsed changelog release entry."""

    version: str
    release_date: date | None
    channel: ReleaseChannel
    summary: str = ""
    added: list[str] = Field(default_factory=list)
    improved: list[str] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    security: list[str] = Field(default_factory=list)
    breaking_changes: list[str] = Field(default_factory=list)
    deprecated: list[str] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)


class ChangelogFormatError(ValueError):
    """Raised when ``CHANGELOG.md`` does not conform to the expected shape."""


# Maps the (case-sensitive, trimmed) text of a "### " heading to the
# corresponding `Release` list field. "Changed" is accepted as a lenient
# synonym for "Improved" per common Keep a Changelog usage.
_SECTION_NAME_TO_FIELD: dict[str, str] = {
    "Added": "added",
    "Improved": "improved",
    "Changed": "improved",
    "Fixed": "fixed",
    # One of Keep a Changelog's six canonical sections, and named by this
    # repo's own changelog policy — it was simply missing here, so the
    # first release to retire a feature failed to parse and took the
    # whole /changelog page down with it.
    "Removed": "removed",
    "Security": "security",
    "Breaking Changes": "breaking_changes",
    "Deprecated": "deprecated",
    "Known Issues": "known_issues",
}

_SECTION_FIELDS: tuple[str, ...] = (
    "added",
    "improved",
    "fixed",
    "removed",
    "security",
    "breaking_changes",
    "deprecated",
    "known_issues",
)

_UNRELEASED_VERSION = "Unreleased"

# Matches the content of a "## " heading after the leading "## " has been
# stripped, e.g. "[Unreleased]", "[1.0.0-beta.1] - 2026-07-26",
# "[1.0.0] - TBD".
_HEADING_CONTENT_RE = re.compile(r"^\[(?P<version>[^\]]+)\](?:\s*-\s*(?P<date>.+))?$")


class _RawRelease(TypedDict):
    version: str
    release_date: date | None
    summary_lines: list[str]
    sections: dict[str, list[str]]


def determine_channel(version: str) -> ReleaseChannel:
    """Derive a release channel from a version's SemVer pre-release identifier.

    No pre-release identifier (no ``-``) → ``"stable"``. Otherwise the text
    immediately after the first ``-`` is inspected: ``beta*`` → ``"beta"``,
    ``rc*`` → ``"release-candidate"``, ``dev*``/``alpha*`` →
    ``"development"``. Any other pre-release identifier is treated as an
    authoring mistake and raises :class:`ChangelogFormatError` rather than
    silently defaulting.
    """
    if "-" not in version:
        return "stable"

    pre_release = version.split("-", 1)[1]

    if pre_release.startswith("beta"):
        return "beta"
    if pre_release.startswith("rc"):
        return "release-candidate"
    if pre_release.startswith("dev") or pre_release.startswith("alpha"):
        return "development"

    raise ChangelogFormatError(
        f"Version '{version}' has an unrecognized pre-release identifier "
        f"'{pre_release}'; expected one starting with 'beta', 'rc', 'dev', or 'alpha'"
    )


def _parse_release_date(version: str, date_text: str | None) -> date | None:
    if date_text is None:
        if version == _UNRELEASED_VERSION:
            return None
        raise ChangelogFormatError(
            f"Release '{version}' is missing a release date (expected 'YYYY-MM-DD' or 'TBD')"
        )

    if date_text == "TBD":
        return None

    try:
        return date.fromisoformat(date_text)
    except ValueError as exc:
        raise ChangelogFormatError(
            f"Release '{version}' has an invalid release date '{date_text}'"
        ) from exc


def _new_raw_release(version: str, release_date: date | None) -> _RawRelease:
    return _RawRelease(
        version=version,
        release_date=release_date,
        summary_lines=[],
        sections={field: [] for field in _SECTION_FIELDS},
    )


def _parse_raw_releases(markdown_text: str) -> list[_RawRelease]:
    """Line-by-line state machine producing one `_RawRelease` per heading.

    Tracks the release heading currently in scope and, within it, which
    recognized subsection (if any) bullets should be appended to. Lines
    before the first "### " heading of a release are treated as the
    release's free-text summary. Wrapped continuation lines (non-bullet
    text following a bullet, as used for long bullet items in the real
    changelog) are folded onto the previous bullet.
    """
    raw_releases: list[_RawRelease] = []
    current: _RawRelease | None = None
    current_field: str | None = None

    for raw_line in markdown_text.splitlines():
        stripped = raw_line.strip()

        if stripped == "":
            continue

        if stripped.startswith("#"):
            # Heading level is the hash *count*, not a literal "## "/"### "
            # prefix match: a heading missing its separating space (e.g.
            # "##[1.0.0]" or "###Fixed") must still be recognized as an
            # attempted release/section heading and rejected, rather than
            # silently falling through to the "document prose" case below
            # with its bullets merged into whatever scope was previously
            # active.
            hash_count = len(stripped) - len(stripped.lstrip("#"))
            rest = stripped[hash_count:]

            if hash_count == 3:
                if not rest.startswith(" "):
                    raise ChangelogFormatError(
                        f"Malformed section heading (missing a space after '###'): " f"'{stripped}'"
                    )
                if current is None:
                    raise ChangelogFormatError(
                        f"Section heading '{stripped}' appears before any release heading"
                    )
                name = rest.strip()
                field = _SECTION_NAME_TO_FIELD.get(name)
                if field is None:
                    raise ChangelogFormatError(
                        f"Unrecognized section '{name}' under version '{current['version']}'"
                    )
                current_field = field
                continue

            if hash_count == 2:
                if not rest.startswith(" "):
                    raise ChangelogFormatError(
                        f"Malformed release heading (missing a space after '##'): " f"'{stripped}'"
                    )
                heading_content = rest.strip()
                match = _HEADING_CONTENT_RE.match(heading_content)
                if match is None:
                    raise ChangelogFormatError(f"Malformed release heading: '## {heading_content}'")
                version = match.group("version").strip()
                date_text = match.group("date")
                date_text = date_text.strip() if date_text is not None else None
                release_date = _parse_release_date(version, date_text)
                current = _new_raw_release(version, release_date)
                raw_releases.append(current)
                current_field = None
                continue

            # Other heading levels (e.g. the top-level "# Changelog" title
            # or its intro paragraph) are document prose, not release data.
            continue

        if current is None:
            # Prose appearing before the first release heading.
            continue

        if current_field is None:
            if stripped.startswith("-"):
                raise ChangelogFormatError(
                    f"Bullet '{stripped}' appears before any '### ' subsection heading "
                    f"under version '{current['version']}'; bullets must be listed "
                    "under a recognized subsection, not in the free-text summary"
                )
            # Free-text summary paragraph for the current release.
            current["summary_lines"].append(stripped)
            continue

        bucket = current["sections"][current_field]
        if stripped.startswith("-"):
            bucket.append(stripped[1:].strip())
        else:
            # Wrapped continuation of the previous bullet's text.
            if bucket:
                bucket[-1] = f"{bucket[-1]} {stripped}".strip()
            else:
                bucket.append(stripped)

    return raw_releases


def _semver_core(version: str) -> tuple[int, int, int]:
    """Parse the MAJOR.MINOR.PATCH numeric core of a SemVer version string.

    Pre-release identifiers are intentionally ignored for this comparison
    per the release-ordering check, which only cares about numeric
    precedence of the core version.
    """
    core = version.split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ChangelogFormatError(
            f"Version '{version}' is not a valid MAJOR.MINOR.PATCH SemVer version"
        )
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _prerelease_sequence(version: str) -> int | None:
    """Extract the trailing numeric sequence from a version's pre-release
    identifier (e.g. ``2`` from ``"1.5.0-beta.2"``), or ``None`` if the
    version has no pre-release identifier or that identifier has no
    trailing digits to compare.
    """
    if "-" not in version:
        return None
    pre_release = version.split("-", 1)[1]
    match = re.search(r"(\d+)$", pre_release)
    return int(match.group(1)) if match else None


def _validate_descending_order(releases: list[Release]) -> None:
    # Every release's version is validated as a well-formed SemVer core —
    # including a changelog with only a single release, which the
    # pairwise `zip` below (empty for a 1-element list) would otherwise
    # never check at all — and no two releases may share the exact same
    # version string (an unambiguous copy-paste mistake regardless of
    # their dates/content).
    seen_versions: set[str] = set()
    cores: list[tuple[int, int, int]] = []
    for release in releases:
        if release.version in seen_versions:
            raise ChangelogFormatError(
                f"Version '{release.version}' is listed more than once in the changelog"
            )
        seen_versions.add(release.version)
        cores.append(_semver_core(release.version))

    for index in range(1, len(releases)):
        previous, current = releases[index - 1], releases[index]
        previous_core, current_core = cores[index - 1], cores[index]

        if current_core > previous_core:
            raise ChangelogFormatError(
                f"Release '{current.version}' has higher SemVer precedence than the "
                f"preceding release '{previous.version}'; releases must be listed in "
                "descending order"
            )

        if current_core == previous_core and current.channel == previous.channel:
            # Two pre-releases (or two stable re-releases, though that
            # case is already caught by the exact-duplicate check above)
            # sharing both core and channel must still appear in
            # descending numeric sequence, e.g. "beta.2" above "beta.1".
            previous_sequence = _prerelease_sequence(previous.version)
            current_sequence = _prerelease_sequence(current.version)
            if (
                previous_sequence is not None
                and current_sequence is not None
                and current_sequence > previous_sequence
            ):
                raise ChangelogFormatError(
                    f"Release '{current.version}' has a higher pre-release sequence "
                    f"number than the preceding release '{previous.version}' despite "
                    "sharing the same version core and channel; releases must be "
                    "listed in descending order"
                )


def parse_changelog(markdown_text: str) -> list[Release]:
    """Parse Keep a Changelog formatted Markdown into a list of `Release`.

    The ``## [Unreleased]`` entry (if present) is parsed like any other
    release — so a malformed Unreleased section still raises
    `ChangelogFormatError` — but is excluded from the returned list since
    it does not represent a shipped release.
    """
    raw_releases = _parse_raw_releases(markdown_text)

    releases: list[Release] = []
    for raw in raw_releases:
        if raw["version"] == _UNRELEASED_VERSION:
            continue

        summary = " ".join(raw["summary_lines"]).strip()
        channel = determine_channel(raw["version"])
        sections = raw["sections"]
        releases.append(
            Release(
                version=raw["version"],
                release_date=raw["release_date"],
                channel=channel,
                summary=summary,
                # Splatted rather than listing each field by hand. Naming
                # them individually meant a section could be added to
                # `_SECTION_FIELDS` and `_SECTION_NAME_TO_FIELD`, parse
                # correctly into `sections`, and still arrive empty here
                # because nobody remembered this third list — which is
                # exactly how `Removed` shipped half-wired.
                **sections,
            )
        )

    _validate_descending_order(releases)
    return releases


def load_releases(path: Path) -> list[Release]:
    """Read ``path`` as UTF-8 text and parse it as a changelog.

    A missing file raises the natural `FileNotFoundError` — it is not
    swallowed here.
    """
    markdown_text = path.read_text(encoding="utf-8")
    return parse_changelog(markdown_text)


def current_release(releases: list[Release]) -> Release | None:
    """Return the current release — the first entry in file order — or None."""
    return releases[0] if releases else None
