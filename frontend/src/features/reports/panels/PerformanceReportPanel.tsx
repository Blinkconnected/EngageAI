import { Card, CardContent, Stack, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { usePerformanceReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { AgentPerformanceRow, DateRange } from '../types'

const COLUMNS: GridColDef<AgentPerformanceRow>[] = [
  { field: 'agent_name', headerName: 'Agent', flex: 1.5 },
  { field: 'conversations_assigned', headerName: 'Assigned', flex: 1, type: 'number' },
  { field: 'conversations_closed', headerName: 'Closed', flex: 1, type: 'number' },
  { field: 'messages_sent', headerName: 'Messages sent', flex: 1, type: 'number' },
]

export function PerformanceReportPanel({ range }: { range: DateRange }) {
  const query = usePerformanceReportQuery(range)

  if (query.isPending) return <LoadingState label="Loading agent performance report…" />
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
          title="No agent activity"
          description="No agent was assigned to or closed a conversation in this date range."
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                Conversations closed by agent
              </Typography>
              <BarChart
                height={300}
                dataset={rows}
                xAxis={[{ dataKey: 'agent_name', scaleType: 'band' }]}
                series={[
                  { dataKey: 'conversations_assigned', label: 'Assigned' },
                  { dataKey: 'conversations_closed', label: 'Closed' },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={COLUMNS}
            getRowId={(row) => row.agent_id}
            ariaLabel="Agent performance report"
          />
        </>
      )}
    </>
  )
}
