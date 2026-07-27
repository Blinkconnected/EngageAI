import { useMemo } from 'react'
import { Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useSlaReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import { StatCard } from '../StatCard'
import type { DateRange, QueueStatsRow } from '../types'

export function SlaReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = useSlaReportQuery(range)

  const columns: GridColDef<QueueStatsRow>[] = useMemo(
    () => [
      { field: 'queue_name', headerName: t('SlaReportPanel.columns.queue'), flex: 1.5 },
      {
        field: 'conversations_entered',
        headerName: t('SlaReportPanel.columns.conversationsEntered'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'sla_breached',
        headerName: t('SlaReportPanel.columns.slaBreaches'),
        flex: 1,
        type: 'number',
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  if (query.isPending) return <LoadingState label={t('SlaReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const data = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons path="/reports/sla" range={range} fallbackFilenameBase="sla-report" />
      </Stack>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <StatCard
          label={t('SlaReportPanel.conversationsOpenedLabel')}
          value={data.conversations_opened}
        />
        <StatCard
          label={t('SlaReportPanel.firstResponseBreachesLabel')}
          value={data.first_response_breached}
        />
        <StatCard
          label={t('SlaReportPanel.resolutionBreachesLabel')}
          value={data.resolution_breached}
        />
      </Grid>

      {data.by_queue.length === 0 ? (
        <EmptyState
          title={t('SlaReportPanel.emptyTitle')}
          description={t('SlaReportPanel.emptyDescription')}
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                {t('SlaReportPanel.chartTitle')}
              </Typography>
              <BarChart
                height={300}
                dataset={data.by_queue.map((row) => ({ ...row }))}
                xAxis={[{ dataKey: 'queue_name', scaleType: 'band' }]}
                series={[
                  { dataKey: 'sla_breached', label: t('SlaReportPanel.slaBreachedSeriesLabel') },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={data.by_queue}
            columns={columns}
            getRowId={(row) => row.queue_id}
            ariaLabel={t('SlaReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}
