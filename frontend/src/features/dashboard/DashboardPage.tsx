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
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { useLiveDashboardQuery } from './api'
import type { AgentWorkload, LiveQueueDepth } from './types'

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
          <Typography variant="h4" component="h2" aria-label={`${label}: ${value}`}>
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
function formatWaitSeconds(seconds: number | null, t: TFunction): string {
  if (seconds == null) return t('DashboardPage.dashPlaceholder')
  const total = Math.round(seconds)
  const minutes = Math.floor(total / 60)
  const remainingSeconds = total % 60
  if (minutes === 0) return t('DashboardPage.secondsFormat', { seconds: remainingSeconds })
  return t('DashboardPage.minutesSecondsFormat', { minutes, seconds: remainingSeconds })
}

function AgentWorkloadTable({ workload }: { workload: AgentWorkload[] }) {
  const { t } = useTranslation('dashboard')
  return (
    <TableContainer>
      <Table size="small" aria-label={t('DashboardPage.teamWorkloadHeading')}>
        <TableHead>
          <TableRow>
            <TableCell>{t('DashboardPage.agentColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.openColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.pendingColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.totalColumnHeader')}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {workload.map((agent) => (
            <TableRow key={agent.agent_id}>
              <TableCell>{agent.agent_name}</TableCell>
              <TableCell align="right">{agent.open_count}</TableCell>
              <TableCell align="right">{agent.pending_count}</TableCell>
              <TableCell align="right">
                {agent.total_count > 0 ? (
                  <Chip label={agent.total_count} size="small" color="primary" />
                ) : (
                  agent.total_count
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function QueueDepthTable({ queues }: { queues: LiveQueueDepth[] }) {
  const { t } = useTranslation('dashboard')
  return (
    <TableContainer>
      <Table size="small" aria-label={t('DashboardPage.queueDepthHeading')}>
        <TableHead>
          <TableRow>
            <TableCell>{t('DashboardPage.queueColumnHeader')}</TableCell>
            <TableCell>{t('DashboardPage.departmentColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.openColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.waitingColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.avgWaitColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.longestWaitingColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.slaBreachedColumnHeader')}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {queues.map((queue) => (
            <TableRow key={queue.queue_id}>
              <TableCell>{queue.queue_name}</TableCell>
              <TableCell>{queue.department_name ?? t('DashboardPage.dashPlaceholder')}</TableCell>
              <TableCell align="right">
                <Chip label={queue.open_conversations} size="small" color="primary" />
              </TableCell>
              <TableCell align="right">{queue.waiting_count}</TableCell>
              <TableCell align="right">{formatWaitSeconds(queue.avg_wait_seconds, t)}</TableCell>
              <TableCell align="right">
                {formatWaitSeconds(queue.longest_wait_seconds, t)}
              </TableCell>
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
  const { t } = useTranslation('dashboard')
  const liveDashboardQuery = useLiveDashboardQuery()

  return (
    <>
      <PageHeader title={t('DashboardPage.title')} description={t('DashboardPage.description')} />

      {liveDashboardQuery.isPending && <LoadingState label={t('DashboardPage.loadingLabel')} />}

      {liveDashboardQuery.isError && (
        <ErrorState error={liveDashboardQuery.error} onRetry={() => liveDashboardQuery.refetch()} />
      )}

      {liveDashboardQuery.data && (
        <Grid container spacing={2}>
          <StatCard
            label={t('DashboardPage.totalConversationsLabel')}
            value={liveDashboardQuery.data.conversations.total}
          />
          <StatCard
            label={t('DashboardPage.activeLabel')}
            value={liveDashboardQuery.data.conversations.active}
          />
          <StatCard
            label={t('DashboardPage.unassignedLabel')}
            value={liveDashboardQuery.data.conversations.unassigned}
          />

          <StatCard
            label={t('DashboardPage.openStatLabel')}
            value={liveDashboardQuery.data.conversations.open}
          />
          <StatCard
            label={t('DashboardPage.pendingStatLabel')}
            value={liveDashboardQuery.data.conversations.pending}
          />
          <StatCard
            label={t('DashboardPage.resolvedLabel')}
            value={liveDashboardQuery.data.conversations.resolved}
          />
          <StatCard
            label={t('DashboardPage.closedLabel')}
            value={liveDashboardQuery.data.conversations.closed}
          />

          <Grid size={{ xs: 12, md: 4 }}>
            <Card variant="outlined">
              <CardContent>
                {/* `component="h3"` — one level under the StatCards' `h2`
                    above, same heading-order rationale as there. */}
                <Typography
                  variant="subtitle1"
                  component="h3"
                  sx={{ fontWeight: 600 }}
                  gutterBottom
                >
                  {t('DashboardPage.agentsHeading')}
                </Typography>
                <Grid container spacing={1}>
                  <Grid size={3}>
                    <Chip
                      label={t('DashboardPage.onlineChip', {
                        num: liveDashboardQuery.data.agents.online,
                      })}
                      color="success"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={t('DashboardPage.awayChip', {
                        num: liveDashboardQuery.data.agents.away,
                      })}
                      color="warning"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={t('DashboardPage.busyChip', {
                        num: liveDashboardQuery.data.agents.busy,
                      })}
                      color="error"
                      variant="outlined"
                      sx={{ width: '100%' }}
                    />
                  </Grid>
                  <Grid size={3}>
                    <Chip
                      label={t('DashboardPage.offlineChip', {
                        num: liveDashboardQuery.data.agents.offline,
                      })}
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
                <Typography
                  variant="subtitle1"
                  component="h3"
                  sx={{ fontWeight: 600 }}
                  gutterBottom
                >
                  {t('DashboardPage.teamWorkloadHeading')}
                </Typography>
                {liveDashboardQuery.data.agent_workload.length === 0 ? (
                  <EmptyState
                    title={t('DashboardPage.noAgentsTitle')}
                    description={t('DashboardPage.noAgentsDescription')}
                  />
                ) : (
                  <AgentWorkloadTable workload={liveDashboardQuery.data.agent_workload} />
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid size={12}>
            <Card variant="outlined">
              <CardContent>
                <Typography
                  variant="subtitle1"
                  component="h3"
                  sx={{ fontWeight: 600 }}
                  gutterBottom
                >
                  {t('DashboardPage.queueDepthHeading')}
                </Typography>
                {liveDashboardQuery.data.queues.length === 0 ? (
                  <EmptyState
                    title={t('DashboardPage.noQueuesTitle')}
                    description={t('DashboardPage.noQueuesDescription')}
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
