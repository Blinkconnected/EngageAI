import { Card, CardContent, Stack, Typography } from '@mui/material'
import { PieChart } from '@mui/x-charts/PieChart'
import type { GridColDef } from '@mui/x-data-grid'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useAiReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { AiOperationRow, DateRange } from '../types'

const COLUMNS: GridColDef<AiOperationRow>[] = [
  { field: 'operation', headerName: 'Operation', flex: 1.5 },
  { field: 'calls', headerName: 'Calls', flex: 1, type: 'number' },
]

export function AiReportPanel({ range }: { range: DateRange }) {
  const query = useAiReportQuery(range)

  if (query.isPending) return <LoadingState label="Loading AI usage report…" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const rows = query.data

  return (
    <>
      <Stack direction="row" sx={{ justifyContent: 'flex-end', mb: 2 }}>
        <ReportExportButtons path="/reports/ai" range={range} fallbackFilenameBase="ai-usage-report" />
      </Stack>

      {rows.length === 0 ? (
        <EmptyState
          title="No AI usage"
          description="No AI feature (reply suggestions, summaries, translation, etc.) was used in this date range."
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                Calls by operation
              </Typography>
              <PieChart
                height={300}
                series={[
                  {
                    data: rows.map((row) => ({ id: row.operation, value: row.calls, label: row.operation })),
                  },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={rows}
            columns={COLUMNS}
            getRowId={(row) => row.operation}
            ariaLabel="AI usage report"
          />
        </>
      )}
    </>
  )
}
