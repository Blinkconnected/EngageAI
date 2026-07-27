import { Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { channelTypeLabel } from '../../channels/types'
import { useExecutiveDashboardQuery } from '../api'
import { ReportExportButtons } from '../ReportExportButtons'
import { StatCard } from '../StatCard'
import type { ConversationStatsRow, DateRange } from '../types'

function aggregateByChannel(rows: ConversationStatsRow[]) {
  const totals = new Map<string, { opened: number; closed: number; resolved: number }>()
  for (const row of rows) {
    const current = totals.get(row.channel_type) ?? { opened: 0, closed: 0, resolved: 0 }
    totals.set(row.channel_type, {
      opened: current.opened + row.opened,
      closed: current.closed + row.closed,
      resolved: current.resolved + row.resolved,
    })
  }
  return Array.from(totals.entries()).map(([channel_type, values]) => ({ channel_type, ...values }))
}

export function ExecutiveDashboardPanel({ range }: { range: DateRange }) {
  const { t } = useTranslation('reportsPanels')
  const query = useExecutiveDashboardQuery(range)

  if (query.isPending) return <LoadingState label={t('ExecutiveDashboardPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const data = query.data
  const channels = aggregateByChannel(data.top_channels)

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons
          path="/reports/executive-dashboard"
          range={range}
          fallbackFilenameBase="executive-dashboard"
        />
      </Stack>

      <Grid container spacing={2}>
        <StatCard
          label={t('ExecutiveDashboardPanel.openedLabel')}
          value={data.conversations_opened}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.closedLabel')}
          value={data.conversations_closed}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.resolvedLabel')}
          value={data.conversations_resolved}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.activeAgentsLabel')}
          value={data.active_agent_count}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.firstResponseBreachesLabel')}
          value={data.first_response_breached}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.resolutionBreachesLabel')}
          value={data.resolution_breached}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.csatAverageLabel')}
          value={data.csat_average_rating != null ? data.csat_average_rating.toFixed(2) : '—'}
        />
        <StatCard
          label={t('ExecutiveDashboardPanel.csatResponsesLabel')}
          value={data.csat_response_count}
        />
        <StatCard label={t('ExecutiveDashboardPanel.aiCallsLabel')} value={data.ai_calls_total} />
      </Grid>

      <Card variant="outlined" sx={{ mt: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
            {t('ExecutiveDashboardPanel.chartTitle')}
          </Typography>
          {channels.length === 0 ? (
            <EmptyState title={t('ExecutiveDashboardPanel.emptyTitle')} />
          ) : (
            <BarChart
              height={320}
              dataset={channels}
              xAxis={[
                {
                  dataKey: 'channel_type',
                  scaleType: 'band',
                  valueFormatter: (value: string) => channelTypeLabel(value),
                },
              ]}
              series={[
                { dataKey: 'opened', label: t('ExecutiveDashboardPanel.openedLabel') },
                { dataKey: 'closed', label: t('ExecutiveDashboardPanel.closedLabel') },
                { dataKey: 'resolved', label: t('ExecutiveDashboardPanel.resolvedLabel') },
              ]}
            />
          )}
        </CardContent>
      </Card>
    </>
  )
}
