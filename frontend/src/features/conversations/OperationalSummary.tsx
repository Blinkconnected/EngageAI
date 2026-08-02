import { memo } from 'react'
import { Box, Skeleton, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { InboxView, Workload } from './inboxTypes'

/** The figures an agent reads first, at 9am, before opening anything.
 *
 * The point is not the numbers — it is whether *today is normal*. A morning
 * with four breached is a different morning from one with none, and that has
 * to arrive before any conversation does.
 *
 * Read once a day and given the most prominent position on the page, which
 * looks backwards until you notice that prominence should follow how much a
 * thing changes a decision, not how often it is looked at.
 */
const HEADLINE: InboxView[] = ['active', 'needs_attention', 'breached']
const SECONDARY: InboxView[] = ['waiting_pickup', 'mine', 'ai_working', 'waiting_customer']

function Figure({
  label,
  value,
  loading,
  emphasis,
}: {
  label: string
  value: number | undefined
  loading: boolean
  emphasis?: 'critical' | 'strong'
}) {
  return (
    <Box sx={{ minWidth: 96 }}>
      <Typography
        variant="h5"
        sx={{
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.1,
          color:
            emphasis === 'critical' && (value ?? 0) > 0
              ? 'error.main'
              : emphasis === 'strong'
                ? 'text.primary'
                : 'text.primary',
        }}
      >
        {loading ? <Skeleton width={40} /> : (value ?? 0)}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
        {label}
      </Typography>
    </Box>
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
    <Box
      component="section"
      aria-label={t('Inbox.summaryAria')}
      sx={{
        px: 2,
        py: 1.5,
        mb: 2,
        borderRadius: 1,
        border: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
      }}
    >
      <Stack
        direction="row"
        spacing={{ xs: 2, sm: 4 }}
        sx={{ flexWrap: 'wrap', rowGap: 1.5, alignItems: 'flex-start' }}
      >
        {HEADLINE.map((view) => (
          <Figure
            key={view}
            label={t(`Inbox.view.${view}`)}
            value={workload?.[view]}
            loading={loading}
            // Breached is the one figure that changes what somebody does
            // this minute, and only when it is not zero — a permanently red
            // number is a number people stop seeing.
            emphasis={view === 'breached' ? 'critical' : 'strong'}
          />
        ))}
        <Box sx={{ flexGrow: 1 }} />
        {SECONDARY.map((view) => (
          <Figure
            key={view}
            label={t(`Inbox.view.${view}`)}
            value={workload?.[view]}
            loading={loading}
          />
        ))}
      </Stack>
    </Box>
  )
})
