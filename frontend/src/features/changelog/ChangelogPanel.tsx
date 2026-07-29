import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Card,
  CardContent,
  Chip,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import SearchIcon from '@mui/icons-material/Search'
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { useReleasesQuery, useVersionQuery } from './api'
import type { Release, ReleaseChannel } from './types'

const CHANNEL_COLOR: Record<ReleaseChannel, 'success' | 'info' | 'warning' | 'default'> = {
  stable: 'success',
  beta: 'info',
  'release-candidate': 'warning',
  development: 'default',
}

function channelLabel(channel: ReleaseChannel, t: TFunction): string {
  switch (channel) {
    case 'stable':
      return t('ChangelogPanel.stableChannelLabel')
    case 'beta':
      return t('ChangelogPanel.betaChannelLabel')
    case 'release-candidate':
      return t('ChangelogPanel.releaseCandidateChannelLabel')
    case 'development':
      return t('ChangelogPanel.developmentChannelLabel')
  }
}

/** Release dates are day-granular (an ISO calendar date, not a timestamp),
 * so this formats a plain calendar date rather than reusing
 * `formatRelativeTime` (used elsewhere for "2 hours ago"-style timestamps). */
function formatReleaseDate(isoDate: string | null, t: TFunction): string {
  if (!isoDate) return t('ChangelogPanel.unreleasedLabel')
  // Parsed and displayed as UTC so the date shown matches the ISO calendar
  // date verbatim regardless of the viewer's timezone — a plain
  // `new Date(isoDate)` would otherwise render a day earlier for any
  // timezone behind UTC.
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

/** CHANGELOG.md entries use Markdown's `**bold**` for a bullet's leading
 * label (e.g. "**Sign-In & Permissions**: ..."). This app has no Markdown
 * renderer elsewhere, and pulling one in for two asterisks isn't worth a
 * new dependency, so this parses just that one construct — anywhere it
 * appears in the string, not only a leading occurrence — into a real
 * `<strong>`, rather than showing the literal `**` characters to readers. */
function renderBulletText(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, index) => {
    const match = /^\*\*([^*]+)\*\*$/.exec(part)
    return match ? <strong key={index}>{match[1]}</strong> : part
  })
}

type SubsectionKey =
  | 'added'
  | 'improved'
  | 'fixed'
  | 'removed'
  | 'security'
  | 'breaking_changes'
  | 'deprecated'
  | 'known_issues'

interface SubsectionSpec {
  key: SubsectionKey
  label: string
  /** Security and Breaking Changes are the sections a reader most needs to
   * notice, so they get an error-tinted heading + icon instead of the
   * plain treatment every other subsection gets. */
  severe?: boolean
}

const SUBSECTION_KEYS: { key: SubsectionKey; severe?: boolean }[] = [
  { key: 'added' },
  { key: 'improved' },
  { key: 'fixed' },
  { key: 'removed' },
  { key: 'security', severe: true },
  { key: 'breaking_changes', severe: true },
  { key: 'deprecated' },
  { key: 'known_issues' },
]

function subsectionLabel(key: SubsectionKey, t: TFunction): string {
  switch (key) {
    case 'added':
      return t('ChangelogPanel.addedLabel')
    case 'improved':
      return t('ChangelogPanel.improvedLabel')
    case 'fixed':
      return t('ChangelogPanel.fixedLabel')
    case 'removed':
      return t('ChangelogPanel.removedLabel')
    case 'security':
      return t('ChangelogPanel.securityLabel')
    case 'breaking_changes':
      return t('ChangelogPanel.breakingChangesLabel')
    case 'deprecated':
      return t('ChangelogPanel.deprecatedLabel')
    case 'known_issues':
      return t('ChangelogPanel.knownIssuesLabel')
  }
}

/** "Major"/"Minor"/"Patch" per SemVer, derived from how a release's
 * MAJOR.MINOR.PATCH core differs from the *previous* (next-older, since
 * releases arrive newest-first) release's core — this is orthogonal to
 * `channel` (which instead reflects the pre-release identifier, e.g.
 * "beta"/"rc"). The very first release in history has nothing to diff
 * against, so it's labeled "Major" (every product's initial release is,
 * by definition, its first major surface). Computed purely client-side
 * from data the backend already returns — no API change needed. */
type ReleaseKind = 'major' | 'minor' | 'patch'

function semverCore(version: string): [number, number, number] | null {
  const core = version.split('-', 1)[0]
  const parts = core!.split('.').map(Number)
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) return null
  return [parts[0]!, parts[1]!, parts[2]!]
}

function coresEqual(a: [number, number, number], b: [number, number, number]): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2]
}

/** `olderReleases` is every release older than `release`, newest-first
 * (i.e. `allReleases.slice(index + 1)`) — several consecutive entries
 * commonly share one core version (e.g. "1.0.0-beta.1", "-beta.2",
 * "-beta.3" all sharing core "1.0.0" ahead of the eventual "1.0.0" GA), so
 * this walks past every same-core sibling to the nearest release whose
 * core actually differs before diffing MAJOR/MINOR/PATCH — comparing
 * against the immediately-preceding entry alone would otherwise call
 * every one of those pre-releases a "Patch" of each other. */
function releaseKind(release: Release, olderReleases: Release[]): ReleaseKind {
  const current = semverCore(release.version)
  if (!current) return 'major'

  const priorDistinctCore = olderReleases
    .map((older) => semverCore(older.version))
    .find((core): core is [number, number, number] => core !== null && !coresEqual(core, current))

  if (!priorDistinctCore) return 'major'
  if (current[0] !== priorDistinctCore[0]) return 'major'
  if (current[1] !== priorDistinctCore[1]) return 'minor'
  return 'patch'
}

function releaseKindLabel(kind: ReleaseKind, t: TFunction): string {
  switch (kind) {
    case 'major':
      return t('ChangelogPanel.majorReleaseLabel')
    case 'minor':
      return t('ChangelogPanel.minorReleaseLabel')
    case 'patch':
      return t('ChangelogPanel.patchReleaseLabel')
  }
}

/** Every bullet-list field on `Release` that counts toward the header's
 * "N features / N improvements / N fixes" summary — deliberately just
 * these three (not security/breaking/deprecated/known-issues, which stay
 * body-only) since those three are what the roadmap asked the collapsed
 * header to surface. */
function releaseCounts(release: Release) {
  return {
    added: release.added.length,
    improved: release.improved.length,
    fixed: release.fixed.length,
  }
}

function releaseAnchorId(version: string): string {
  return `release-${version}`
}

/** Flattened, lowercased searchable text for one release — every bullet
 * across every subsection, plus the summary and version, so a search
 * term matches regardless of which subsection it lives in. Recomputed
 * once per release per render of the (memoized) filter, not per
 * keystroke against the DOM. */
function releaseSearchText(release: Release): string {
  return [
    release.version,
    release.summary,
    ...release.added,
    ...release.improved,
    ...release.fixed,
    ...release.security,
    ...release.breaking_changes,
    ...release.deprecated,
    ...release.known_issues,
  ]
    .join(' \n ')
    .toLowerCase()
}

function ReleaseSubsection({ spec, items }: { spec: SubsectionSpec; items: string[] }) {
  if (items.length === 0) return null

  return (
    <Box sx={{ mt: 2 }}>
      {/* `component="h4"` — one level under each release's own `h3`
          heading in the accordion summary, same heading-order rationale
          DashboardPage.tsx documents for its h2/h3 pair. */}
      <Typography
        variant="subtitle2"
        component="h4"
        sx={{
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          color: spec.severe ? 'error.main' : 'text.primary',
        }}
      >
        {spec.severe && <ReportProblemOutlinedIcon fontSize="inherit" aria-hidden="true" />}
        {spec.label}
      </Typography>
      <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 3 }}>
        {items.map((item) => (
          <Typography key={item} component="li" variant="body2" color="text.secondary">
            {renderBulletText(item)}
          </Typography>
        ))}
      </Box>
    </Box>
  )
}

interface ReleaseAccordionItemProps {
  release: Release
  kind: ReleaseKind
  expanded: boolean
  onToggle: () => void
}

function ReleaseAccordionItem({ release, kind, expanded, onToggle }: ReleaseAccordionItemProps) {
  const { t } = useTranslation('changelog')
  const counts = releaseCounts(release)

  return (
    <Accordion
      id={releaseAnchorId(release.version)}
      expanded={expanded}
      onChange={onToggle}
      variant="outlined"
      disableGutters
      // Collapsed release bodies are removed from the DOM entirely, not
      // just visually hidden — the roadmap requires this page to "stay
      // performant with hundreds of releases," and a changelog with real
      // history quickly accumulates far more releases than a user will
      // ever expand in one visit.
      slotProps={{ transition: { unmountOnExit: true } }}
      sx={{
        '&:before': { display: 'none' },
        scrollMarginTop: (theme) => theme.spacing(2),
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1, width: '100%', pr: 1 }}
        >
          {/* `component="h3"` — one level under this panel's own `h1`
              heading below, same heading-order rationale as
              DashboardPage.tsx's StatCard headings. */}
          <Typography variant="h6" component="h3" sx={{ fontWeight: 600 }}>
            {release.version}
          </Typography>
          <Chip
            label={releaseKindLabel(kind, t)}
            size="small"
            variant="outlined"
            color={kind === 'major' ? 'primary' : 'default'}
          />
          <Chip
            label={channelLabel(release.channel, t)}
            size="small"
            color={CHANNEL_COLOR[release.channel]}
          />
          <Typography variant="body2" color="text.secondary">
            {formatReleaseDate(release.release_date, t)}
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
            {counts.added > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={t('ChangelogPanel.newFeaturesCount', { count: counts.added })}
              />
            )}
            {counts.improved > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={t('ChangelogPanel.improvementsCount', { count: counts.improved })}
              />
            )}
            {counts.fixed > 0 && (
              <Chip
                size="small"
                variant="outlined"
                label={t('ChangelogPanel.bugFixesCount', { count: counts.fixed })}
              />
            )}
          </Stack>
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        {release.summary && (
          <Typography variant="body2" sx={{ mb: 1 }}>
            {renderBulletText(release.summary)}
          </Typography>
        )}
        {SUBSECTION_KEYS.map((spec) => (
          <ReleaseSubsection
            key={spec.key}
            spec={{ key: spec.key, label: subsectionLabel(spec.key, t), severe: spec.severe }}
            items={release[spec.key]}
          />
        ))}
      </AccordionDetails>
    </Accordion>
  )
}

/**
 * The changelog's actual rendering logic, extracted so it can be mounted
 * anywhere (currently: the public login page — see LoginPage.tsx) without
 * a page chrome of its own. There is deliberately no `PageHeader` here;
 * the host page provides the page-level `h1` (this component's own "What's
 * new" heading is that `h1` on LoginPage, since that page previously had
 * none — see the heading-order comments below).
 */
export function ChangelogPanel() {
  const { t } = useTranslation('changelog')
  const versionQuery = useVersionQuery()
  const releasesQuery = useReleasesQuery()

  const isPending = versionQuery.isPending || releasesQuery.isPending
  const isError = versionQuery.isError || releasesQuery.isError
  const error = versionQuery.error ?? releasesQuery.error

  const [searchTerm, setSearchTerm] = useState('')
  // The set of versions the user has manually expanded/collapsed. A Set
  // (not "expand all but this list of collapsed ones") because a search
  // results in only the *matching* subset being in the DOM at all, so
  // tracking "which of the currently-visible releases are expanded" is
  // the simpler, always-correct model. `null` means "not yet initialized
  // from the first successful releases fetch" — see the memo below,
  // which derives the one-time initial value from render (not an effect)
  // since it's plain derived state, not a subscription to an external
  // system.
  const [expandedVersions, setExpandedVersions] = useState<Set<string> | null>(null)

  // Deep link support: a URL like `/changelog#release-1.0.0-beta.2`
  // expands that specific release by default instead of the newest one
  // — see the scroll-into-view effect below for the rest of that
  // behavior. A hash fragment (not a route param) was chosen because it
  // works from any link to this page, including the public
  // unauthenticated one, with no routing changes.
  const deepLinkedVersion = useMemo(() => {
    if (!releasesQuery.data) return null
    const hashVersion = decodeURIComponent(window.location.hash.replace(/^#release-/, ''))
    return releasesQuery.data.find((release) => release.version === hashVersion)?.version ?? null
  }, [releasesQuery.data])

  const resolvedExpandedVersions = useMemo(() => {
    if (expandedVersions !== null) return expandedVersions
    if (!releasesQuery.data || releasesQuery.data.length === 0) return new Set<string>()
    return new Set([deepLinkedVersion ?? releasesQuery.data[0]!.version])
  }, [expandedVersions, releasesQuery.data, deepLinkedVersion])

  useEffect(() => {
    if (!deepLinkedVersion) return
    // Deferred one frame so the accordion has mounted (and, since it's
    // newly expanded, measured its now-taller height) before the browser
    // is asked to scroll to it.
    const frame = requestAnimationFrame(() => {
      document.getElementById(releaseAnchorId(deepLinkedVersion))?.scrollIntoView({ block: 'start' })
    })
    return () => cancelAnimationFrame(frame)
  }, [deepLinkedVersion])

  function toggleExpanded(version: string) {
    setExpandedVersions((previous) => {
      const next = new Set(previous ?? resolvedExpandedVersions)
      if (next.has(version)) next.delete(version)
      else next.add(version)
      return next
    })
  }

  const releaseKinds = useMemo(() => {
    const data = releasesQuery.data ?? []
    const kinds = new Map<string, ReleaseKind>()
    data.forEach((release, index) => {
      kinds.set(release.version, releaseKind(release, data.slice(index + 1)))
    })
    return kinds
  }, [releasesQuery.data])

  const filteredReleases = useMemo(() => {
    const data = releasesQuery.data ?? []
    const term = searchTerm.trim().toLowerCase()
    if (!term) return data
    return data.filter((release) => releaseSearchText(release).includes(term))
  }, [releasesQuery.data, searchTerm])

  return (
    <Box>
      {/* `component="h1"` — LoginPage has no heading of its own, so this
          panel's title is the page's single top-level heading; every
          heading below descends from it (h2 -> h3 -> h4), never skipping
          a level, matching DashboardPage.tsx's documented discipline. */}
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700, mb: 2 }}>
        {t('ChangelogPanel.title')}
      </Typography>

      {isPending && <LoadingState label={t('ChangelogPanel.loadingLabel')} />}

      {isError && (
        <ErrorState
          error={error}
          onRetry={() => {
            void versionQuery.refetch()
            void releasesQuery.refetch()
          }}
        />
      )}

      {versionQuery.data && (
        <Card variant="outlined" sx={{ mb: 3 }}>
          <CardContent>
            {/* `component="h2"` — directly under this panel's own `h1`
                above, same heading-order rationale as DashboardPage.tsx's
                StatCard headings. */}
            <Typography color="text.secondary" variant="body2" gutterBottom>
              {t('ChangelogPanel.currentlyRunningLabel')}
            </Typography>
            <Stack
              component="div"
              direction="row"
              spacing={1.5}
              sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}
            >
              <Typography variant="h5" component="h2" sx={{ fontWeight: 600 }}>
                {versionQuery.data.version}
              </Typography>
              <Chip
                label={channelLabel(versionQuery.data.release_channel, t)}
                size="small"
                color={CHANNEL_COLOR[versionQuery.data.release_channel]}
              />
              <Typography variant="body2" color="text.secondary">
                {t('ChangelogPanel.releasedLabel', {
                  date: formatReleaseDate(versionQuery.data.release_date, t),
                })}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      {releasesQuery.data &&
        (releasesQuery.data.length === 0 ? (
          <EmptyState
            title={t('ChangelogPanel.noReleasesTitle')}
            description={t('ChangelogPanel.noReleasesDescription')}
          />
        ) : (
          <Box>
            <TextField
              fullWidth
              size="small"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder={t('ChangelogPanel.searchPlaceholder')}
              sx={{ mb: 2 }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                },
                htmlInput: { 'aria-label': t('ChangelogPanel.searchAriaLabel') },
              }}
            />

            {filteredReleases.length === 0 ? (
              <EmptyState
                title={t('ChangelogPanel.noSearchResultsTitle')}
                description={t('ChangelogPanel.noSearchResultsDescription', { searchTerm })}
              />
            ) : (
              <Stack spacing={1.5}>
                {filteredReleases.map((release) => (
                  <ReleaseAccordionItem
                    key={release.version}
                    release={release}
                    kind={releaseKinds.get(release.version) ?? 'major'}
                    expanded={resolvedExpandedVersions.has(release.version)}
                    onToggle={() => toggleExpanded(release.version)}
                  />
                ))}
              </Stack>
            )}
          </Box>
        ))}
    </Box>
  )
}
