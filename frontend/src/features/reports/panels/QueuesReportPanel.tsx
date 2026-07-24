import { Card, CardContent, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useQueuesReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { DateRange, QueueStatsRow } from '../types'

const COLUMNS: GridColDef<QueueStatsRow>[] = [
  { field: 'queue_name', headerName: 'Queue', flex: 1.5 },
  { field: 'conversations_entered', headerName: 'Conversations entered', flex: 1, type: 'number' },
  { field: 'sla_breached', headerName: 'SLA breaches', flex: 1, type: 'number' },
]

export function QueuesReportPanel({ range }: { range: DateRange }) {
  const query = useQueuesReportQuery(range)

  if (query.isPending) return <LoadingState label="Loading queues report…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const rows = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons path="/reports/queues" range={range} fallbackFilenameBase="queues-report" />
      </Stack>

      {rows.length === 0 ? (
        <EmptyState
          title="No queue activity"
          description="No conversation entered a queue in this date range."
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                Queue volume and SLA breaches
              </Typography>
              <BarChart
                height={300}
                dataset={rows}
                xAxis={[{ dataKey: 'queue_name', scaleType: 'band' }]}
                series={[
                  { dataKey: 'conversations_entered', label: 'Entered' },
                  { dataKey: 'sla_breached', label: 'SLA breached' },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={COLUMNS}
            getRowId={(row) => row.queue_id}
            ariaLabel="Queues report"
          />
        </>
      )}
    </>
  )
}
