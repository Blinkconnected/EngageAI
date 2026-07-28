# Release Versioning & Changelog

How the running application knows its own version, how `CHANGELOG.md` is
written and parsed, and how that surfaces through the public version/
release API and the frontend Changelog page. Referenced directly from
`CHANGELOG.md`'s own intro paragraph — this is that referenced doc.

## What exists

- **`/CHANGELOG.md`** (repo root) — the single source of truth for the
  product's release history, written in
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format and
  [Semantic Versioning](https://semver.org/). Written in plain,
  non-technical language deliberately — this file is public (see below)
  and is read by non-engineers, not just developers.
- **`core/changelog.py`** — a small line-by-line parser (not a generic
  Markdown library — the accepted shape is narrow and specific, so a
  hand-written state machine can validate it strictly and name exactly
  what's wrong when a changelog entry is malformed, rather than silently
  producing incomplete data) turning the file into a list of `Release`
  objects.
- **`api/v1/endpoints/version.py`** — two deliberately unauthenticated
  endpoints (`GET /api/v1/version`, `GET /api/v1/releases`) exposing the
  parsed data — see decision #1 below for why these have no auth
  requirement.
- **`frontend/src/features/changelog/`** — `ChangelogPanel` (the actual
  rendering: current-version summary + release history cards) and
  `ChangelogPage` (a thin, standalone, public wrapper around it, routed
  at `/changelog` outside `ProtectedRoute`). Linked from the login page
  ("What's new in this release").

## Changelog file format the parser accepts

```
# Changelog
<intro prose — ignored by the parser, for human readers only>

## [Unreleased]

### Added
- (nothing yet)

## [1.0.0-beta.1] - 2026-07-26
<optional free-text summary paragraph(s)>

### Added
- **Bold label**: description. Long bullets may wrap onto continuation
  lines with no leading `-`; the parser folds them back onto the
  previous bullet.
- Another bullet.

### Known Issues
- ...

## [1.0.0] - TBD
<summary>
```

Recognized `### ` section names (case-sensitive): `Added`, `Improved`,
`Changed` (accepted as a lenient synonym for `Improved`), `Fixed`,
`Security`, `Breaking Changes`, `Deprecated`, `Known Issues`. Anything
else raises `ChangelogFormatError` naming the offending heading — a
typo'd section name fails loudly at parse time (and at app startup, per
decision #2) rather than silently dropping content.

A release's `## [version] - date` heading's date is either an ISO
`YYYY-MM-DD` or the literal `TBD` (renders as `null`/"Unreleased" to
consumers) — `## [Unreleased]` itself is the one heading allowed to omit
a date entirely, and is parsed like any other release (so a malformed
`Unreleased` section still fails loudly) but excluded from
`parse_changelog`'s returned list since it isn't a shipped release.

## Key decisions

1. **`GET /version`/`GET /releases` require no authentication**,
   deliberately: this is the same class of information a status page,
   load balancer health check, or support engineer needs to be able to
   read without a credential — matching `GET /health`'s existing
   unauthenticated precedent. The frontend Changelog page inherits this:
   it's a standalone public route, not nested behind `ProtectedRoute`,
   linked from the login page specifically so a visitor can see what's
   new before ever signing in.

2. **A changelog that fails to parse fails the app's own startup**, not
   just the two endpoints that read it. `main.py`'s `create_app()` calls
   `current_release(load_releases(...))` at startup and raises if it
   returns `None` (no published release entries) — the same "fail fast on
   a broken invariant" bar as the CORS-wildcard check next to it. Serving
   traffic under a wrong/placeholder version silently would make every
   downstream consumer of `GET /version` (status pages, support tooling,
   `test_version_consistency.py`'s own tripwire) trust a lie. A
   missing/malformed `CHANGELOG.md` is always an operator/deployment
   error, never client-triggerable, so at request time (as opposed to
   startup) the same failure maps to `503`, not an unhandled `500` —
   see `version.py`'s `_load_releases_or_503`.

3. **A release's channel (`stable`/`beta`/`release-candidate`/
   `development`) is derived from its version string, never
   hand-authored as a separate field.** No pre-release identifier ->
   `stable`; `-beta*` -> `beta`; `-rc*` -> `release-candidate`;
   `-dev*`/`-alpha*` -> `development`. One fact (the version string)
   instead of two facts that could drift out of sync (version + a
   separately-maintained channel label).

4. **Three files must agree on the current version**:
   `CHANGELOG.md`'s topmost published release, `backend/pyproject.toml`'s
   `[project].version`, and `frontend/package.json`'s `"version"`.
   `backend/tests/unit/test_version_consistency.py` is a tripwire test
   reading all three directly (not through the API) that fails the
   moment any one drifts — release procedure is to bump all three
   together, by hand, in lockstep; there is no single generated source
   for this repo's three independent packaging manifests.

5. **Build metadata (`git_commit`, `build_timestamp`, `docker_image_tag`)
   is populated by the CI/CD pipeline, not computed by the app itself.**
   `.github/workflows/ci.yml`'s release build passes `GIT_COMMIT`/
   `BUILD_TIMESTAMP`/`DOCKER_IMAGE_TAG` as Docker build args (see
   `docker/backend/Dockerfile`'s `base` stage), which become `Settings`
   defaults (`git_commit`/`build_timestamp`/`docker_image_tag`) baked into
   the image. Local `docker compose` development has no build pipeline to
   inject these, so they stay at their harmless defaults
   (`"unknown"`/`"development"`).

6. **The plain-language rewrite of `CHANGELOG.md`'s prose is a
   deliberate, ongoing writing constraint, not a one-time cleanup.** This
   file is read by non-technical stakeholders directly (via the public
   Changelog page), so every new entry avoids engineering jargon
   (JWT, RBAC, WebSocket, webhook, API, SemVer-as-acronym, etc.) in favor
   of what a feature actually does for the business — the parser doesn't
   enforce this (it only validates structure), so it's a review-time
   discipline, not a lint rule.

## Frontend rendering notes

- `CHANGELOG.md` bullets use Markdown's `**bold**` for a leading label
  (e.g. `**Conversations**: ...`). This app has no Markdown renderer
  elsewhere and pulling one in for two asterisks isn't worth a new
  dependency, so `ChangelogPanel.tsx`'s `renderBulletText` parses just
  that one construct into a real `<strong>` — anywhere it appears in a
  bullet or summary, not only a leading occurrence.
- `ChangelogPanel` has no `PageHeader` of its own (that component assumes
  it's rendered inside `AppLayout`'s content area); it renders its own
  top-level heading ("What's new") instead, since `ChangelogPage` mounts
  it standalone, outside `AppLayout` entirely.

### Accordion, search, and deep linking (Beta 4)

Each release renders as an MUI `Accordion` instead of a flat `Card` —
only the newest release starts expanded (older ones collapse by
default), and a collapsed release's `AccordionDetails` is fully
unmounted (`slotProps={{ transition: { unmountOnExit: true } }}`), not
just visually hidden, so a changelog with real history (this repo's own
already has 4+ entries) stays cheap regardless of how many releases
accumulate.

- **Header counts** ("N new features / N improvements / N bug fixes")
  are `.length` on the `Release` model's existing `added`/`improved`/
  `fixed` arrays — no backend change needed, since the parser already
  returns these as structured lists.
- **Release type** (Major/Minor/Patch) is derived client-side by diffing
  a release's SemVer core against the nearest *older* release with a
  genuinely different core (`releaseKind` in `ChangelogPanel.tsx`) —
  several consecutive pre-releases commonly share one core (e.g.
  `1.0.0-beta.1`/`-beta.2`/`-beta.3` all sharing core `1.0.0` ahead of
  the eventual `1.0.0` GA), so comparing only against the immediately
  preceding entry would misclassify every one of them as a "Patch" of
  each other. This is orthogonal to `channel`, which instead reflects
  the pre-release identifier (`beta`/`rc`/etc.).
- **Search** filters the release list client-side against a flattened,
  lowercased join of every release's version, summary, and every bullet
  across every subsection — matching-only releases render; a "No
  matching releases" empty state covers the zero-match case. Not a
  backend search endpoint: the full release history is small and already
  fetched in one unpaginated request (see decision above on
  `GET /releases`), so filtering already-loaded data client-side avoids a
  round trip for what is, in practice, a few hundred short strings at
  most.
- **Deep linking** uses a `#release-<version>` URL hash fragment (e.g.
  `/changelog#release-1.0.0-beta.2`), not a route param — read directly
  from `window.location.hash` on first load, expanding and scrolling to
  that specific release instead of defaulting to "newest expanded." A
  hash fragment (rather than adding a `/changelog/:version` route) works
  from any link to this already-public page, including links shared
  before a visitor has ever signed in, with no routing changes.

## Verification performed

Backend: 42 tests — parser edge cases (malformed headings, out-of-order
releases, duplicate versions, unrecognized sections, wrapped-bullet
folding, channel derivation for every prefix), the two endpoints'
success/503 paths (missing file, malformed content, no published
releases), and the three-file version-consistency tripwire. Frontend:
`ChangelogPanel`/`ChangelogPage`/`LoginPage` tests (loading/error/empty
states, the bold-label parsing fix, the public-route link, axe
accessibility checks) — full suite 171 passing, `tsc`/`eslint` clean,
production build succeeds.

**Known limitation**: this repo's development environment resolves the
`backend` service's `CHANGELOG.md` bind mount (`docker-compose.yml`)
against a filesystem view that can lag behind the actual repo-root file
in some sandboxed setups — confirmed via a full container
remove-and-recreate that still served stale content. This is an
environment quirk, not a defect in the compose file itself, which is
correct for a normal deployment; a real container rebuild-and-redeploy
picks up the current file.

**Beta 4 verification**: 4 new frontend tests (release-type label +
new-feature count rendering in a collapsed header, search filtering the
visible list, the no-results empty state, and `#release-<version>` deep
linking to a non-newest release) plus 2 existing tests updated for the
"only the newest release starts expanded" behavior — full changelog
suite 11 passing, full frontend suite 279 passing, `tsc`/`eslint` clean,
production build succeeds. Live-verified against the running Docker
stack: `GET /api/v1/releases` returns this repo's real (non-mock)
release history — `1.0.0-beta.3`, `1.0.0-beta.2`, `1.0.0-beta.1` — at the
time of this milestone, confirming the accordion/search/collapse
behavior was built and tested against a realistic multi-release shape,
not just the two-release test fixture.
