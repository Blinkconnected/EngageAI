import { Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { LineChart } from '@mui/x-charts/LineChart'
import type { GridColDef } from '@mui/x-data-grid'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useCsatReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import { StatCard } from '../StatCard'
import type { CsatAgentRow, DateRange } from '../types'

const COLUMNS: GridColDef<CsatAgentRow>[] = [
  { field: 'agent_name', headerName: 'Agent', flex: 1.5 },
  { field: 'response_count', headerName: 'Responses', flex: 1, type: 'number' },
  {
    field: 'average_rating',
    headerName: 'Average rating',
    flex: 1,
    type: 'number',
    valueFormatter: (value: number | null) => (value != null ? value.toFixed(2) : '—'),
  },
]

export function CsatReportPanel({ range }: { range: DateRange }) {
  const query = useCsatReportQuery(range)

  if (query.isPending) return <LoadingState label="Loading CSAT report…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const data = query.data
  const trend = data.daily_trend.filter((row) => row.average_rating != null)

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons path="/reports/csat" range={range} fallbackFilenameBase="csat-report" />
      </Stack>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <StatCard
          label="Average rating"
          value={data.average_rating != null ? data.average_rating.toFixed(2) : '—'}
        />
        <StatCard label="Responses" value={data.response_count} />
      </Grid>

      {data.response_count === 0 ? (
        <EmptyState
          title="No CSAT responses"
          description="No customer submitted a satisfaction rating in this date range."
        />
      ) : (
        <>
          {trend.length > 0 && (
            <Card variant="outlined" sx={{ mb: 3 }}>
              <CardContent>
                <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                  Average rating over time
                </Typography>
                <LineChart
                  height={300}
                  dataset={trend.map((row) => ({ ...row }))}
                  xAxis={[{ dataKey: 'stat_date', scaleType: 'point' }]}
                  series={[{ dataKey: 'average_rating', label: 'Average rating' }]}
                />
              </CardContent>
            </Card>
          )}
          <ReportDataGrid
            rows={data.by_agent}
            columns={COLUMNS}
            getRowId={(row) => row.agent_id}
            ariaLabel="CSAT by agent"
          />
        </>
      )}
    </>
  )
}
