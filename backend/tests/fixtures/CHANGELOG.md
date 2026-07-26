# Changelog

Test fixture for the version/release API and the version-consistency
tripwire test — deliberately small and stable, and completely separate
from the real, ever-growing `/CHANGELOG.md` at the repo root. Do not
edit this file to reflect real product changes.

## [Unreleased]

### Added
- Placeholder unreleased change, never surfaced by the version API.

## [2.0.0] - 2026-01-01

Second stable fixture release.

### Added
- Widget dashboard
- CSV export

### Improved
- Faster search indexing

### Fixed
- Fixed pagination off-by-one on the queue list

### Known Issues
- Search results are capped at 500 rows

## [2.0.0-beta.1] - 2025-12-01

Beta fixture release preceding 2.0.0.

### Security
- Hardened session cookie flags

### Breaking Changes
- Renamed `legacy_id` field to `external_id`

### Deprecated
- Legacy `/v0/widgets` endpoint
