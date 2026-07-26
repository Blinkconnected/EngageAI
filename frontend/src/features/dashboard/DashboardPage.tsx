import {
  Card,
  CardContent,
  Chip,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { useLiveDashboardQuery } from './api'
import type { LiveQueueDepth } from './types'

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
      <Card variant="outlined">
        <CardContent>
          <Typography color="text.secondary" gutterBottom>
            {label}
          </Typography>
          {/* `component="h2"` keeps this a real heading directly under the
              page's own `<h1>` (PageHeader) — the default h4 tag this
              variant would otherwise render as skips two levels, which is
              what an axe accessibility pass flags as a heading-order
              violation. */}
          <Typography variant="h4" component="h2">
            {value}
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  )
}

/** `waiting_count`/`sla_breached_count` are exact integers, but
 * `avg_wait_seconds`/`longest_wait_seconds` are computed averages the
 * backend returns as floats — rounding here is purely a display concern
 * (the raw value is still what gets sent anywhere it matters). */
function formatWaitSeconds(seconds: number | null): string {
  if (seconds == null) return '—'
  const total = Math.round(seconds)
  const minutes = Math.floor(total / 60)
  const remainingSeconds = total % 60
  if (minutes === 0) return `${remainingSeconds}s`
  return `${minutes}m ${remainingSeconds}s`
}

function QueueDepthTable({ queues }: { queues: LiveQueueDepth[] }) {
  return (
    <TableContainer>
      <Table size="small" aria-label="Queue depth">
        <TableHead>
          <TableRow>
            <TableCell>Queue</TableCell>
            <TableCell>Department</TableCell>
            <TableCell align="right">Open</TableCell>
            <TableCell align="right">Waiting</TableCell>
            <TableCell align="right">Avg wait</TableCell>
            <TableCell align="right">Longest waiting</TableCell>
            <TableCell align="right">SLA breached</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {queues.map((queue) => (
            <TableRow key={queue.queue_id}>
              <TableCell>{queue.queue_name}</TableCell>
              <TableCell>{queue.department_name ?? '—'}</TableCell>
              <TableCell align="right">
                <Chip label={queue.open_conversations} size="small" color="primary" />
              </TableCell>
              <TableCell align="right">{queue.waiting_count}</TableCell>
              <TableCell align="right">{formatWaitSeconds(queue.avg_wait_seconds)}</TableCell>
              <TableCell align="right">{formatWaitSeconds(queue.longest_wait_seconds)}</TableCell>
              <TableCell align="right">
                {queue.sla_breached_count > 0 ? (
                  <Chip label={queue.sla_breached_count} size="small" color="error" />
                ) : (
                  queue.sla_breached_count
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export function DashboardPage() {
  const liveDashboardQuery = useLiveDashboardQuery()

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="A live snapshot of conversations, agents, and queues across your company."
      />

      {liveDashboardQuery.isPending && <LoadingState label="Loading live dashboard…" />}

      {liveDashboardQuery.isError && (
        <ErrorState error={liveDashboardQuery.error} onRetry={() => liveDashboardQuery.refetch()} />
      )}

      {liveDashboardQuery.data && (
        <Grid container spacing={2}>
          <StatCard label="Open conversations" value={liveDashboardQuery.data.conversations.open} />
          <StatCard label="Pending" value={liveDashboardQuery.data.conversations.pending} />
          <StatCard label="Resolved" value={liveDashboardQuery.data.conversations.resolved} />
          <StatCard label="Closed" value={liveDashboardQuery.data.conversations.closed} />

          <Grid size={{ xs: 12, md: 4 }}>
            <Card variant="outlined">
              <CardContent>
                {/* `component="h3"` — one level under the StatCards' `h2`
                    above, same heading-order rationale as there. */}
                <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 600 }} gutterBottom>
                  Agents
                </Typography>
                <Grid container spacing={1}>
                  <Grid size={3}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.online} online`}
                      color="success"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.away} away`}
                      color="warning"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.busy} busy`}
                      color="error"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.offline} offline`}
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 8 }}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 600 }} gutterBottom>
                  Queue depth
                </Typography>
                {liveDashboardQuery.data.queues.length === 0 ? (
                  <EmptyState
                    title="No queues yet"
                    description="Queues will appear here once conversations start routing through them."
                  />
                ) : (
                  <QueueDepthTable queues={liveDashboardQuery.data.queues} />
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}
    </>
  )
}
