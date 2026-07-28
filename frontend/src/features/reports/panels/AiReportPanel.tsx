import { useMemo, useState } from 'react'
import {
  Card,
  CardContent,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { PieChart } from '@mui/x-charts/PieChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useAiReportQuery, useAiUsageReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type {
  AiAgentUsageRow,
  AiOperationRow,
  AiUsageGranularity,
  DateRange,
} from '../types'

export function AiReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const [granularity, setGranularity] = useState<AiUsageGranularity>('daily')
  const query = useAiReportQuery(range)
  // A second, independent query rather than replacing the first: the
  // by-operation grid and both export formats still consume
  // /reports/ai's flat array, and this panel shows both.
  const usageQuery = useAiUsageReportQuery(range, granularity)

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

  const agentColumns: GridColDef<AiAgentUsageRow>[] = useMemo(
    () => [
      { field: 'agent_name', headerName: t('AiReportPanel.columns.agent'), flex: 1.5 },
      {
        field: 'total_calls',
        headerName: t('AiReportPanel.columns.totalCalls'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'autopilot_agent_requests',
        headerName: t('AiReportPanel.columns.autopilotRequested'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'autopilot_sla_triggers',
        headerName: t('AiReportPanel.columns.autopilotSla'),
        flex: 1,
        type: 'number',
      },
    ],
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

          <Card variant="outlined" sx={{ mt: 3 }}>
            <CardContent>
              <Stack
                direction="row"
                sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
              >
                <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
                  {t('AiReportPanel.trendTitle')}
                </Typography>
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={granularity}
                  onChange={(_event, value: AiUsageGranularity | null) => {
                    if (value) setGranularity(value)
                  }}
                  aria-label={t('AiReportPanel.granularityAriaLabel')}
                >
                  <ToggleButton value="daily">{t('AiReportPanel.granularityDaily')}</ToggleButton>
                  <ToggleButton value="weekly">{t('AiReportPanel.granularityWeekly')}</ToggleButton>
                  <ToggleButton value="monthly">
                    {t('AiReportPanel.granularityMonthly')}
                  </ToggleButton>
                </ToggleButtonGroup>
              </Stack>
              {usageQuery.data && usageQuery.data.trend.length > 0 ? (
                <BarChart
                  height={280}
                  xAxis={[
                    {
                      scaleType: 'band',
                      data: usageQuery.data.trend.map((bucket) => bucket.bucket_start),
                    },
                  ]}
                  series={[
                    {
                      data: usageQuery.data.trend.map((bucket) => bucket.calls),
                      label: t('AiReportPanel.columns.calls'),
                    },
                  ]}
                />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t('AiReportPanel.noTrendData')}
                </Typography>
              )}
            </CardContent>
          </Card>

          <Card variant="outlined" sx={{ mt: 3 }}>
            <CardContent>
              <Typography
                variant="subtitle1"
                component="h2"
                sx={{ fontWeight: 600 }}
                gutterBottom
              >
                {t('AiReportPanel.byAgentTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {t('AiReportPanel.byAgentDescription')}
              </Typography>
              {usageQuery.data && usageQuery.data.by_agent.length > 0 ? (
                <ReportDataGrid
                  rows={usageQuery.data.by_agent}
                  columns={agentColumns}
                  getRowId={(row) => row.agent_id}
                  ariaLabel={t('AiReportPanel.byAgentGridAriaLabel')}
                />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t('AiReportPanel.noAgentUsage')}
                </Typography>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </>
  )
}
