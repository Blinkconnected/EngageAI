import { isAxiosError } from 'axios'
import { Grid } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useAgentDashboardQuery } from '../api'
import { StatCard } from '../StatCard'
import type { DateRange } from '../types'

/** Own-stats view for agents. No export — the backend doesn't offer one on
 * this endpoint (it's a personal snapshot, not a shareable report). */
export function MyPerformancePanel({ range }: { range: DateRange }) {
  const { t } = useTranslation('reportsPanels')
  const query = useAgentDashboardQuery(range)

  if (query.isPending) return <LoadingState label={t('MyPerformancePanel.loadingLabel')} />

  if (query.isError) {
    if (isAxiosError(query.error) && query.error.response?.status === 404) {
      return (
        <EmptyState
          title={t('MyPerformancePanel.noProfileTitle')}
          description={t('MyPerformancePanel.noProfileDescription')}
        />
      )
    }
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  }

  const data = query.data

  return (
    <Grid container spacing={2}>
      <StatCard
        label={t('MyPerformancePanel.conversationsAssignedLabel')}
        value={data.conversations_assigned}
      />
      <StatCard
        label={t('MyPerformancePanel.conversationsClosedLabel')}
        value={data.conversations_closed}
      />
      <StatCard label={t('MyPerformancePanel.messagesSentLabel')} value={data.messages_sent} />
    </Grid>
  )
}
