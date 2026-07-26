import { Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material'
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined'
import { PageHeader } from '../../shared/components/PageHeader'
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

const CHANNEL_LABEL: Record<ReleaseChannel, string> = {
  stable: 'Stable',
  beta: 'Beta',
  'release-candidate': 'Release candidate',
  development: 'Development',
}

/** Release dates are day-granular (an ISO calendar date, not a timestamp),
 * so this formats a plain calendar date rather than reusing
 * `formatRelativeTime` (used elsewhere for "2 hours ago"-style timestamps). */
function formatReleaseDate(isoDate: string | null): string {
  if (!isoDate) return 'Unreleased'
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

type SubsectionKey =
  | 'added'
  | 'improved'
  | 'fixed'
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

const SUBSECTIONS: SubsectionSpec[] = [
  { key: 'added', label: 'Added' },
  { key: 'improved', label: 'Improved' },
  { key: 'fixed', label: 'Fixed' },
  { key: 'security', label: 'Security', severe: true },
  { key: 'breaking_changes', label: 'Breaking Changes', severe: true },
  { key: 'deprecated', label: 'Deprecated' },
  { key: 'known_issues', label: 'Known Issues' },
]

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
            {item}
          </Typography>
        ))}
      </Box>
    </Box>
  )
}

function ReleaseCard({ release }: { release: Release }) {
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
            label={CHANNEL_LABEL[release.channel]}
            size="small"
            color={CHANNEL_COLOR[release.channel]}
          />
          <Typography variant="body2" color="text.secondary">
            {formatReleaseDate(release.release_date)}
          </Typography>
        </Stack>

        {release.summary && (
          <Typography variant="body2" sx={{ mt: 1.5 }}>
            {release.summary}
          </Typography>
        )}

        {SUBSECTIONS.map((spec) => (
          <ReleaseSubsection key={spec.key} spec={spec} items={release[spec.key]} />
        ))}
      </CardContent>
    </Card>
  )
}

export function ChangelogPage() {
  const versionQuery = useVersionQuery()
  const releasesQuery = useReleasesQuery()

  const isPending = versionQuery.isPending || releasesQuery.isPending
  const isError = versionQuery.isError || releasesQuery.isError
  const error = versionQuery.error ?? releasesQuery.error

  return (
    <>
      <PageHeader
        title="Changelog"
        description="Release history and what's new in Blink Engage."
      />

      {isPending && <LoadingState label="Loading changelog…" />}

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
            {/* `component="h2"` — directly under the page's own `<h1>`
                (PageHeader), same heading-order rationale DashboardPage.tsx
                documents for its StatCard headings. */}
            <Typography color="text.secondary" variant="body2" gutterBottom>
              Currently running
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
                label={CHANNEL_LABEL[versionQuery.data.release_channel]}
                size="small"
                color={CHANNEL_COLOR[versionQuery.data.release_channel]}
              />
              <Typography variant="body2" color="text.secondary">
                Released {formatReleaseDate(versionQuery.data.release_date)}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      {releasesQuery.data &&
        (releasesQuery.data.length === 0 ? (
          <EmptyState
            title="No releases yet"
            description="Published release history will appear here once a release is cut."
          />
        ) : (
          <Stack spacing={2}>
            {releasesQuery.data.map((release) => (
              <ReleaseCard key={release.version} release={release} />
            ))}
          </Stack>
        ))}
    </>
  )
}
