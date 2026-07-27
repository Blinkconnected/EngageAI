import { useMemo } from 'react'
import { Card, CardContent, Stack, Typography } from '@mui/material'
import { PieChart } from '@mui/x-charts/PieChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useAiReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { AiOperationRow, DateRange } from '../types'

export function AiReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = useAiReportQuery(range)

  const columns: GridColDef<AiOperationRow>[] = useMemo(
    () => [
      { field: 'operation', headerName: t('AiReportPanel.columns.operation'), flex: 1.5 },
      { field: 'calls', headerName: t('AiReportPanel.columns.calls'), flex: 1, type: 'number' },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  if (query.isPending) return <LoadingState label={t('AiReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const rows = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons
          path="/reports/ai"
          range={range}
          fallbackFilenameBase="ai-usage-report"
        />
      </Stack>

      {rows.length === 0 ? (
        <EmptyState
          title={t('AiReportPanel.emptyTitle')}
          description={t('AiReportPanel.emptyDescription')}
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                {t('AiReportPanel.chartTitle')}
              </Typography>
              <PieChart
                height={300}
                series={[
                  {
                    data: rows.map((row) => ({
                      id: row.operation,
                      value: row.calls,
                      label: row.operation,
                    })),
                  },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={columns}
            getRowId={(row) => row.operation}
            ariaLabel={t('AiReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}
