import {
  Card,
  CardContent,
  Chip,
  Grid,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { useLiveDashboardQuery } from './api'

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
      <Card variant="outlined">
        <CardContent>
          <Typography color="text.secondary" gutterBottom>
            {label}
          </Typography>
          <Typography variant="h4">{value}</Typography>
        </CardContent>
      </Card>
    </Grid>
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
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>
                  Agents
                </Typography>
                <Grid container spacing={1}>
                  <Grid size={4}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.online} online`}
                      color="success"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={4}>
                    <Chip
                      label={`${liveDashboardQuery.data.agents.away} away`}
                      color="warning"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={4}>
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
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>
                  Queue depth
                </Typography>
                {liveDashboardQuery.data.queues.length === 0 ? (
                  <EmptyState
                    title="No queues yet"
                    description="Queues will appear here once conversations start routing through them."
                  />
                ) : (
                  <List dense>
                    {liveDashboardQuery.data.queues.map((queue) => (
                      <ListItem
                        key={queue.queue_id}
                        secondaryAction={
                          <Chip label={queue.open_conversations} size="small" color="primary" />
                        }
                      >
                        <ListItemText primary={queue.queue_name} />
                      </ListItem>
                    ))}
                  </List>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}
    </>
  )
}
