import { useMemo } from 'react'
import { Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { LineChart } from '@mui/x-charts/LineChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useCsatReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import { StatCard } from '../StatCard'
import type { CsatAgentRow, DateRange } from '../types'

export function CsatReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = useCsatReportQuery(range)

  const columns: GridColDef<CsatAgentRow>[] = useMemo(
    () => [
      { field: 'agent_name', headerName: t('CsatReportPanel.agentColumn'), flex: 1.5 },
      {
        field: 'response_count',
        headerName: t('CsatReportPanel.responsesLabel'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'average_rating',
        headerName: t('CsatReportPanel.averageRatingLabel'),
        flex: 1,
        type: 'number',
        valueFormatter: (value: number | null) => (value != null ? value.toFixed(2) : '—'),
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  if (query.isPending) return <LoadingState label={t('CsatReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const data = query.data
  const trend = data.daily_trend.filter((row) => row.average_rating != null)

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons
          path="/reports/csat"
          range={range}
          fallbackFilenameBase="csat-report"
        />
      </Stack>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <StatCard
          label={t('CsatReportPanel.averageRatingLabel')}
          value={data.average_rating != null ? data.average_rating.toFixed(2) : '—'}
        />
        <StatCard label={t('CsatReportPanel.responsesLabel')} value={data.response_count} />
      </Grid>

      {data.response_count === 0 ? (
        <EmptyState
          title={t('CsatReportPanel.emptyTitle')}
          description={t('CsatReportPanel.emptyDescription')}
        />
      ) : (
        <>
          {trend.length > 0 && (
            <Card variant="outlined" sx={{ mb: 3 }}>
              <CardContent>
                <Typography
                  variant="subtitle1"
                  component="h2"
                  sx={{ fontWeight: 600 }}
                  gutterBottom
                >
                  {t('CsatReportPanel.chartTitle')}
                </Typography>
                <LineChart
                  height={300}
                  dataset={trend.map((row) => ({ ...row }))}
                  xAxis={[{ dataKey: 'stat_date', scaleType: 'point' }]}
                  series={[
                    { dataKey: 'average_rating', label: t('CsatReportPanel.averageRatingLabel') },
                  ]}
                />
              </CardContent>
            </Card>
          )}
          <ReportDataGrid
            rows={data.by_agent}
            columns={columns}
            getRowId={(row) => row.agent_id}
            ariaLabel={t('CsatReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}
