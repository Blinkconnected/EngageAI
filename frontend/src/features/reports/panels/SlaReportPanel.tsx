import { Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useSlaReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import { StatCard } from '../StatCard'
import type { DateRange, QueueStatsRow } from '../types'

const COLUMNS: GridColDef<QueueStatsRow>[] = [
  { field: 'queue_name', headerName: 'Queue', flex: 1.5 },
  { field: 'conversations_entered', headerName: 'Conversations entered', flex: 1, type: 'number' },
  { field: 'sla_breached', headerName: 'SLA breaches', flex: 1, type: 'number' },
]

export function SlaReportPanel({ range }: { range: DateRange }) {
  const query = useSlaReportQuery(range)

  if (query.isPending) return <LoadingState label="Loading SLA report…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const data = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons path="/reports/sla" range={range} fallbackFilenameBase="sla-report" />
      </Stack>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <StatCard label="Conversations opened" value={data.conversations_opened} />
        <StatCard label="1st response breaches" value={data.first_response_breached} />
        <StatCard label="Resolution breaches" value={data.resolution_breached} />
      </Grid>

      {data.by_queue.length === 0 ? (
        <EmptyState
          title="No queue activity"
          description="No conversation entered a queue in this date range."
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                SLA breaches by queue
              </Typography>
              <BarChart
                height={300}
                dataset={data.by_queue.map((row) => ({ ...row }))}
                xAxis={[{ dataKey: 'queue_name', scaleType: 'band' }]}
                series={[{ dataKey: 'sla_breached', label: 'SLA breached' }]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={data.by_queue}
            columns={COLUMNS}
            getRowId={(row) => row.queue_id}
            ariaLabel="SLA breaches by queue"
          />
        </>
      )}
    </>
  )
}
