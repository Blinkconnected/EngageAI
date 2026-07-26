from datetime import date
from pathlib import Path

import pytest

from blinkengage.core.changelog import (
    ChangelogFormatError,
    Release,
    current_release,
    determine_channel,
    load_releases,
    parse_changelog,
)

FIXTURE_BASIC = """\
# Changelog

Intro paragraph, ignored by the parser.

## [Unreleased]

### Added
- (nothing yet)

## [2.0.0] - 2026-05-01

Second major release, focused on reporting and export.

### Added
- Executive dashboard
- SLA reports

### Fixed
- Fixed timezone handling in scheduled reports

### Known Issues
- Excel export is slow for very large date ranges

## [1.5.0-beta.2] - 2026-02-15

Beta preview of the workflow engine.

### Added
- Workflow engine condition/action automation

### Security
- Hardened webhook signature verification

### Deprecated
- Legacy `/v0/workflows` endpoint
"""


def test_parses_basic_fixture_excluding_unreleased() -> None:
    releases = parse_changelog(FIXTURE_BASIC)

    assert [r.version for r in releases] == ["2.0.0", "1.5.0-beta.2"]

    stable = releases[0]
    assert stable.release_date == date(2026, 5, 1)
    assert stable.channel == "stable"
    assert stable.summary == "Second major release, focused on reporting and export."
    assert stable.added == ["Executive dashboard", "SLA reports"]
    assert stable.fixed == ["Fixed timezone handling in scheduled reports"]
    assert stable.known_issues == ["Excel export is slow for very large date ranges"]
    assert stable.improved == []
    assert stable.security == []
    assert stable.breaking_changes == []
    assert stable.deprecated == []

    beta = releases[1]
    assert beta.release_date == date(2026, 2, 15)
    assert beta.channel == "beta"
    assert beta.summary == "Beta preview of the workflow engine."
    assert beta.added == ["Workflow engine condition/action automation"]
    assert beta.security == ["Hardened webhook signature verification"]
    assert beta.deprecated == ["Legacy `/v0/workflows` endpoint"]
    assert beta.fixed == []
    assert beta.known_issues == []


def test_tbd_date_parses_to_none() -> None:
    fixture = """\
## [1.0.0] - TBD

Stable release pending validation.

### Added
- Placeholder
"""
    releases = parse_changelog(fixture)

    assert len(releases) == 1
    assert releases[0].release_date is None


@pytest.mark.parametrize(
    ("version", "expected_channel"),
    [
        ("1.0.0", "stable"),
        ("1.0.0-beta.3", "beta"),
        ("2.1.0-rc.2", "release-candidate"),
        ("1.0.0-dev.1", "development"),
        ("1.0.0-alpha.1", "development"),
    ],
)
def test_determine_channel(version: str, expected_channel: str) -> None:
    assert determine_channel(version) == expected_channel


def test_determine_channel_raises_on_unrecognized_prerelease_tag() -> None:
    with pytest.raises(
        ChangelogFormatError,
        match=r"unrecognized pre-release identifier 'nonsense\.1'",
    ):
        determine_channel("1.0.0-nonsense.1")


def test_section_with_zero_bullets_is_empty_list() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

Release with an empty section.

### Added
### Fixed
- Something fixed
"""
    releases = parse_changelog(fixture)

    assert releases[0].added == []
    assert releases[0].fixed == ["Something fixed"]


def test_section_never_mentioned_defaults_to_empty_list() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Added
- Something
"""
    releases = parse_changelog(fixture)

    release = releases[0]
    assert release.security == []
    assert release.improved == []
    assert release.breaking_changes == []
    assert release.deprecated == []
    assert release.known_issues == []


def test_breaking_changes_heading_maps_to_breaking_changes_field() -> None:
    fixture = """\
## [2.0.0] - 2026-01-01

### Breaking Changes
- Removed the legacy `/v0/customers` endpoint
"""
    releases = parse_changelog(fixture)

    assert releases[0].breaking_changes == ["Removed the legacy `/v0/customers` endpoint"]


def test_free_text_summary_captured_not_dropped() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

This is the first line of the summary.
This is the second line of the summary.

### Added
- Something
"""
    releases = parse_changelog(fixture)

    assert releases[0].summary == (
        "This is the first line of the summary. This is the second line of the summary."
    )


def test_changed_heading_is_synonym_for_improved() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Changed
- Updated default page size to 50
"""
    releases = parse_changelog(fixture)

    assert releases[0].improved == ["Updated default page size to 50"]
    assert releases[0].added == []


def test_unrecognized_section_heading_raises() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### NotARealSection
- Bad
"""
    with pytest.raises(ChangelogFormatError, match="NotARealSection"):
        parse_changelog(fixture)


def test_out_of_order_versions_raise() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Added
- Something

## [2.0.0] - 2026-02-01

### Added
- Something else
"""
    with pytest.raises(
        ChangelogFormatError,
        match=r"Release '2\.0\.0' has higher SemVer precedence than the preceding "
        r"release '1\.0\.0'",
    ):
        parse_changelog(fixture)


def test_current_release_empty_list_returns_none() -> None:
    assert current_release([]) is None


def test_current_release_returns_first_element() -> None:
    release_a = Release(version="2.0.0", release_date=date(2026, 5, 1), channel="stable")
    release_b = Release(version="1.5.0-beta.2", release_date=date(2026, 2, 15), channel="beta")

    assert current_release([release_a, release_b]) is release_a


def test_load_releases_round_trips_against_a_real_file(tmp_path: Path) -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

Stable release.

### Added
- Something shipped
"""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(fixture, encoding="utf-8")

    releases = load_releases(changelog_path)

    assert len(releases) == 1
    assert releases[0].version == "1.0.0"
    assert releases[0].channel == "stable"
    assert releases[0].added == ["Something shipped"]


def test_load_releases_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_releases(tmp_path / "does-not-exist.md")


def test_release_heading_missing_space_after_hashes_raises() -> None:
    fixture = """\
## [2.0.0] - 2026-02-01

### Added
- Something in 2.0.0

##[1.0.0] - 2026-01-01

### Added
- Something in 1.0.0
"""
    with pytest.raises(ChangelogFormatError, match="missing a space after '##'"):
        parse_changelog(fixture)


def test_section_heading_missing_space_after_hashes_raises() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

###Fixed
- Something
"""
    with pytest.raises(ChangelogFormatError, match="missing a space after '###'"):
        parse_changelog(fixture)


def test_bare_hash_marks_with_no_space_or_content_raise() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

##
"""
    with pytest.raises(ChangelogFormatError, match="missing a space after '##'"):
        parse_changelog(fixture)


def test_duplicate_exact_version_raises() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Added
- First entry

## [1.0.0] - 2026-02-01

### Added
- Duplicate entry
"""
    with pytest.raises(ChangelogFormatError, match="listed more than once"):
        parse_changelog(fixture)


def test_same_core_same_channel_out_of_sequence_prereleases_raise() -> None:
    fixture = """\
## [1.5.0-beta.1] - 2026-02-01

### Added
- Something

## [1.5.0-beta.2] - 2026-01-01

### Added
- Something earlier
"""
    with pytest.raises(ChangelogFormatError, match="pre-release sequence"):
        parse_changelog(fixture)


def test_stray_bullet_before_first_subsection_raises() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01
- stray bullet acting as summary

### Added
- Foo
"""
    with pytest.raises(ChangelogFormatError, match="appears before any '### ' subsection"):
        parse_changelog(fixture)


def test_release_heading_missing_date_raises() -> None:
    fixture = """\
## [1.0.0]

### Added
- Something
"""
    with pytest.raises(ChangelogFormatError, match="missing a release date"):
        parse_changelog(fixture)


@pytest.mark.parametrize("date_text", ["05/01/2026", "not-a-date"])
def test_release_heading_invalid_date_raises(date_text: str) -> None:
    fixture = f"""\
## [1.0.0] - {date_text}

### Added
- Something
"""
    with pytest.raises(ChangelogFormatError, match="invalid release date"):
        parse_changelog(fixture)


def test_section_heading_before_any_release_heading_raises() -> None:
    fixture = """\
### Added
- Something premature

## [1.0.0] - 2026-01-01
"""
    with pytest.raises(ChangelogFormatError, match="appears before any release heading"):
        parse_changelog(fixture)


@pytest.mark.parametrize("heading", ["Random prose", "1.0.0"])
def test_release_heading_without_brackets_raises(heading: str) -> None:
    fixture = f"## {heading}\n"
    with pytest.raises(ChangelogFormatError, match="Malformed release heading"):
        parse_changelog(fixture)


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "banana"])
def test_semver_core_rejects_non_semver_versions_even_as_the_only_release(
    version: str,
) -> None:
    # A single-release changelog must still be rejected for a garbage
    # version — the pairwise descending-order comparison alone (`zip`
    # over an empty tail for a 1-element list) would never catch this.
    fixture = f"""\
## [{version}] - 2026-01-01

### Added
- Something
"""
    with pytest.raises(ChangelogFormatError, match="not a valid MAJOR.MINOR.PATCH"):
        parse_changelog(fixture)


def test_section_content_without_leading_dash_is_accepted_verbatim() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Added
Some text with no leading dash
"""
    releases = parse_changelog(fixture)

    assert releases[0].added == ["Some text with no leading dash"]
