import { isAxiosError } from 'axios'
import { Grid } from '@mui/material'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { useAgentDashboardQuery } from '../api'
import { StatCard } from '../StatCard'
import type { DateRange } from '../types'

/** Own-stats view for agents. No export — the backend doesn't offer one on
 * this endpoint (it's a personal snapshot, not a shareable report). */
export function MyPerformancePanel({ range }: { range: DateRange }) {
  const query = useAgentDashboardQuery(range)

  if (query.isPending) return <LoadingState label="Loading your performance…" />

  if (query.isError) {
    if (isAxiosError(query.error) && query.error.response?.status === 404) {
      return (
        <EmptyState
          title="No agent profile"
          description="Your account isn't linked to an agent profile, so there's no personal performance data to show."
        />
      )
    }
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  }

  const data = query.data

  return (
    <Grid container spacing={2}>
      <StatCard label="Conversations assigned" value={data.conversations_assigned} />
      <StatCard label="Conversations closed" value={data.conversations_closed} />
      <StatCard label="Messages sent" value={data.messages_sent} />
    </Grid>
  )
}
