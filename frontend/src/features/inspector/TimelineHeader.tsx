import { memo } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TimelineEvent } from './types'

function timeOf(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** The one line a reader scans: when, who, what.
 *
 * The time is monospaced and tabular so the column reads straight down —
 * a timeline whose timestamps jitter horizontally is one people stop
 * scanning and start reading, which is slower.
 */
const SEVERITY_COLOR = {
  success: 'success',
  warning: 'warning',
  error: 'error',
  critical: 'error',
} as const

export const TimelineHeader = memo(function TimelineHeader({ event }: { event: TimelineEvent }) {
  const { t } = useTranslation('inspector')
  const severity = event.severity === 'info' ? null : event.severity

  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{ alignItems: 'baseline', flexWrap: 'wrap', rowGap: 0.5 }}
    >
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontVariantNumeric: 'tabular-nums', fontFamily: 'monospace' }}
      >
        {timeOf(event.at)}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {event.title}
      </Typography>
      <Chip size="small" variant="outlined" label={event.actor} sx={{ height: 20 }} />
      {/* The severity the *backend* assigned, as words and not only as a
          colour: a ring alone is invisible to a screen reader and to the
          ~8% of men with a red-green deficiency, on the one column that
          says whether something went wrong. */}
      {severity ? (
        <Chip
          size="small"
          color={SEVERITY_COLOR[severity]}
          variant={severity === 'critical' ? 'filled' : 'outlined'}
          label={t(`severity.${severity}`)}
          sx={{ height: 20 }}
        />
      ) : null}
      <Box sx={{ flexGrow: 1 }} />
    </Stack>
  )
})
