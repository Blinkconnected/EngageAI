import type { ReactNode } from 'react'
import { Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material'
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
  'added' | 'improved' | 'fixed' | 'security' | 'breaking_changes' | 'deprecated' | 'known_issues'

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

function ReleaseSubsection({ spec, items }: { spec: SubsectionSpec; items: string[] }) {
  if (items.length === 0) return null

  return (
    <Box sx={{ mt: 2 }}>
      {/* `component="h4"` — one level under each release card's own `h3`
          heading below, same heading-order rationale DashboardPage.tsx
          documents for its h2/h3 pair. */}
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

function ReleaseCard({ release }: { release: Release }) {
  const { t } = useTranslation('changelog')
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack
          component="div"
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}
        >
          {/* `component="h3"` — one level under the version-summary card's
              `h2` above, same heading-order rationale as there. */}
          <Typography variant="h6" component="h3" sx={{ fontWeight: 600 }}>
            {release.version}
          </Typography>
          <Chip
            label={channelLabel(release.channel, t)}
            size="small"
            color={CHANNEL_COLOR[release.channel]}
          />
          <Typography variant="body2" color="text.secondary">
            {formatReleaseDate(release.release_date, t)}
          </Typography>
        </Stack>

        {release.summary && (
          <Typography variant="body2" sx={{ mt: 1.5 }}>
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
      </CardContent>
    </Card>
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
          <Stack spacing={2}>
            {releasesQuery.data.map((release) => (
              <ReleaseCard key={release.version} release={release} />
            ))}
          </Stack>
        ))}
    </Box>
  )
}
