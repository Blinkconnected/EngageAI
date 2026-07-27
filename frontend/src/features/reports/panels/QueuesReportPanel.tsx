import { useMemo } from 'react'
import { Card, CardContent, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useQueuesReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { DateRange, QueueStatsRow } from '../types'

export function QueuesReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = useQueuesReportQuery(range)

  const columns: GridColDef<QueueStatsRow>[] = useMemo(
    () => [
      { field: 'queue_name', headerName: t('QueuesReportPanel.columns.queue'), flex: 1.5 },
      {
        field: 'conversations_entered',
        headerName: t('QueuesReportPanel.columns.conversationsEntered'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'sla_breached',
        headerName: t('QueuesReportPanel.columns.slaBreaches'),
        flex: 1,
        type: 'number',
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  if (query.isPending) return <LoadingState label={t('QueuesReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const rows = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons
          path="/reports/queues"
          range={range}
          fallbackFilenameBase="queues-report"
        />
      </Stack>

      {rows.length === 0 ? (
        <EmptyState
          title={t('QueuesReportPanel.emptyTitle')}
          description={t('QueuesReportPanel.emptyDescription')}
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                {t('QueuesReportPanel.chartTitle')}
              </Typography>
              <BarChart
                height={300}
                dataset={rows.map((row) => ({ ...row }))}
                xAxis={[{ dataKey: 'queue_name', scaleType: 'band' }]}
                series={[
                  {
                    dataKey: 'conversations_entered',
                    label: t('QueuesReportPanel.enteredSeriesLabel'),
                  },
                  { dataKey: 'sla_breached', label: t('QueuesReportPanel.slaBreachedSeriesLabel') },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={columns}
            getRowId={(row) => row.queue_id}
            ariaLabel={t('QueuesReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}
