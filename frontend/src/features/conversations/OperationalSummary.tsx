import { memo } from 'react'
import { Box, Skeleton, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { InboxView, Workload } from './inboxTypes'

/** Whether today is normal, in one line.
 *
 * This used to be a band of seven large figures above the queues. The
 * figures were not wrong, they were *duplicated*: every one of them also
 * appears inside its own queue chip immediately below, so the same seven
 * numbers were on screen twice and the work itself started a third of
 * the way down the page. Two of them answer a question the chips do not
 * — how much is there in total, and how much of it has already failed —
 * so those two stayed and the rest went.
 *
 * Read once a morning, which is exactly why it must not cost a third of
 * the screen for the rest of the day.
 */
const HEADLINE: InboxView[] = ['active', 'breached']

function Figure({
  label,
  value,
  loading,
  critical,
}: {
  label: string
  value: number | undefined
  loading: boolean
  critical?: boolean
}) {
  return (
    <Stack direction="row" spacing={0.75} sx={{ alignItems: 'baseline' }}>
      <Typography
        component="span"
        variant="subtitle2"
        sx={{
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          // Red only when it is not zero. A permanently red number is a
          // number people stop seeing.
          color: critical && (value ?? 0) > 0 ? 'error.main' : 'text.primary',
        }}
      >
        {loading ? <Skeleton width={18} sx={{ display: 'inline-block' }} /> : (value ?? 0)}
      </Typography>
      <Typography component="span" variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Stack>
  )
}

export const OperationalSummary = memo(function OperationalSummary({
  workload,
  loading = false,
}: {
  workload: Workload | undefined
  loading?: boolean
}) {
  const { t } = useTranslation('conversationsCore')

  return (
    <Stack
      component="section"
      direction="row"
      spacing={2}
      aria-label={t('Inbox.summaryAria')}
      sx={{ alignItems: 'baseline', flexWrap: 'wrap', rowGap: 0.5 }}
    >
      {HEADLINE.map((view) => (
        <Figure
          key={view}
          label={t(`Inbox.view.${view}`).toLowerCase()}
          value={workload?.[view]}
          loading={loading}
          critical={view === 'breached'}
        />
      ))}
      <Box sx={{ flexGrow: 1 }} />
    </Stack>
  )
})
