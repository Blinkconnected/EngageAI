import { useMemo } from 'react'
import { Card, CardContent, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { usePerformanceReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { AgentPerformanceRow, DateRange } from '../types'

export function PerformanceReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = usePerformanceReportQuery(range)

  const columns: GridColDef<AgentPerformanceRow>[] = useMemo(
    () => [
      { field: 'agent_name', headerName: t('PerformanceReportPanel.columns.agent'), flex: 1.5 },
      {
        field: 'conversations_assigned',
        headerName: t('PerformanceReportPanel.assignedLabel'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'conversations_closed',
        headerName: t('PerformanceReportPanel.closedLabel'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'messages_sent',
        headerName: t('PerformanceReportPanel.columns.messagesSent'),
        flex: 1,
        type: 'number',
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  if (query.isPending) return <LoadingState label={t('PerformanceReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const rows = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons
          path="/reports/performance"
          range={range}
          fallbackFilenameBase="agent-performance-report"
        />
      </Stack>

      {rows.length === 0 ? (
        <EmptyState
          title={t('PerformanceReportPanel.emptyTitle')}
          description={t('PerformanceReportPanel.emptyDescription')}
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                {t('PerformanceReportPanel.chartTitle')}
              </Typography>
              <BarChart
                height={300}
                dataset={rows.map((row) => ({ ...row }))}
                xAxis={[{ dataKey: 'agent_name', scaleType: 'band' }]}
                series={[
                  {
                    dataKey: 'conversations_assigned',
                    label: t('PerformanceReportPanel.assignedLabel'),
                  },
                  {
                    dataKey: 'conversations_closed',
                    label: t('PerformanceReportPanel.closedLabel'),
                  },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={columns}
            getRowId={(row) => row.agent_id}
            ariaLabel={t('PerformanceReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}
