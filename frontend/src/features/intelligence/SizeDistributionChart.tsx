import { Box, Card, CardContent, LinearProgress, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { SizeDistribution } from './types'

/** The shape of the corpus, as bars an operator can read at a glance.
 *
 * A mean cannot distinguish "twenty healthy clusters" from "one enormous
 * cluster and nineteen singletons", and those need opposite responses —
 * so the distribution is shown rather than summarised. Mass in the 1–2
 * buckets means the join threshold is too high to group anything; one
 * bucket at 100+ holding most of the corpus means it is too low to
 * separate anything.
 *
 * Bars rather than a charting library: seven buckets is not a chart, and
 * a dependency for it would be seven buckets of overhead.
 */
export function SizeDistributionChart({ data }: { data: SizeDistribution }) {
  const { t } = useTranslation('intelligence')
  const entries = Object.entries(data.buckets)
  const largest = Math.max(1, ...entries.map(([, count]) => count))

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          {t('SizeDistribution.title')}
        </Typography>
        {data.total === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('SizeDistribution.empty')}
          </Typography>
        ) : (
          <Stack spacing={1} sx={{ mt: 1 }}>
            {entries.map(([bucket, count]) => (
              <Box key={bucket}>
                <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                  <Typography variant="caption" color="text.secondary">
                    {t('SizeDistribution.bucketLabel', { bucket })}
                  </Typography>
                  <Typography variant="caption">{count}</Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={(count / largest) * 100}
                  // Singletons are the failure signal, so they are
                  // coloured as one rather than left to be counted.
                  color={bucket === '1' && count > 0 ? 'warning' : 'primary'}
                  sx={{ height: 6, borderRadius: 1 }}
                />
              </Box>
            ))}
            <Typography variant="caption" color="text.secondary" sx={{ pt: 1 }}>
              {t('SizeDistribution.summary', {
                median: data.median ?? '—',
                p90: data.p90 ?? '—',
                largest: data.largest ?? '—',
              })}
            </Typography>
          </Stack>
        )}
      </CardContent>
    </Card>
  )
}
