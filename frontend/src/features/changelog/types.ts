/** A release's maturity, derived by the backend from its version's SemVer
 * pre-release identifier (no suffix -> `stable`; `-beta.N` -> `beta`;
 * `-rc.N` -> `release-candidate`; `-dev.N`/`-alpha.N` -> `development`). */
export type ReleaseChannel = 'development' | 'beta' | 'release-candidate' | 'stable'

/** Matches the backend's `VersionResponse` (`GET /version`) — the identity
 * of the currently running release, for status pages and troubleshooting. */
export interface VersionInfo {
  product: string
  version: string
  build: string
  git_commit: string
  release_date: string | null
  release_channel: ReleaseChannel
  docker_image_tag: string
}

/** Matches the backend's `Release` model (`GET /releases`) — a single
 * parsed `CHANGELOG.md` entry. The "Unreleased" entry is excluded by the
 * backend itself, so every `Release` returned here is a shipped release.
 * Every array field below can legitimately be empty — only `version`,
 * `release_date`, and `channel` are guaranteed present/meaningful. */
export interface Release {
  version: string
  release_date: string | null
  channel: ReleaseChannel
  summary: string
  added: string[]
  improved: string[]
  fixed: string[]
  removed: string[]
  security: string[]
  breaking_changes: string[]
  deprecated: string[]
  known_issues: string[]
}
