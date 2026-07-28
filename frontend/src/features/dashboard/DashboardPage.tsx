import { useMemo } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Button,
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useLiveDashboardQuery } from './api'
import type { AgentWorkload, LiveQueueDepth } from './types'

function StatCard({
  label,
  value,
  alertWhenNonZero = false,
}: {
  label: string
  value: number
  /** Draws the card in the error color once `value` is above zero —
   * for stats where any non-zero figure is itself the problem (SLA
   * breaches), not just a number to read. Deliberately silent at zero,
   * the same "only deviations earn emphasis" rule the redesigned Inbox
   * follows (see docs/architecture/frontend.md). */
  alertWhenNonZero?: boolean
}) {
  const alerting = alertWhenNonZero && value > 0
  return (
    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
      <Card variant="outlined" sx={alerting ? { borderColor: 'error.main' } : undefined}>
        <CardContent>
          <Typography color="text.secondary" gutterBottom>
            {label}
          </Typography>
          {/* `component="h2"` keeps this a real heading directly under the
              page's own `<h1>` (PageHeader) — the default h4 tag this
              variant would otherwise render as skips two levels, which is
              what an axe accessibility pass flags as a heading-order
              violation. */}
          <Typography
            variant="h4"
            component="h2"
            color={alerting ? 'error.main' : undefined}
            aria-label={`${label}: ${value}`}
          >
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

function sumQueues(queues: LiveQueueDepth[], key: keyof LiveQueueDepth): number {
  return queues.reduce((total, queue) => total + (queue[key] as number), 0)
}

/** Company-wide funnel across every queue — waiting/picked/active are the
 * current pipeline; resolved/closed are the last 24h of throughput out of
 * it. Gives supervisors the "conversation flow" overview the per-queue
 * table below can't at a glance. */
function QueueFlowChart({ queues, t }: { queues: LiveQueueDepth[]; t: TFunction }) {
  const dataset = useMemo(
    () => [
      {
        stage: t('DashboardPage.waitingColumnHeader'),
        value: sumQueues(queues, 'waiting_count'),
      },
      {
        stage: t('DashboardPage.pickedColumnHeader'),
        value: sumQueues(queues, 'picked_count'),
      },
      {
        stage: t('DashboardPage.activeColumnHeader'),
        value: sumQueues(queues, 'active_count'),
      },
      {
        stage: t('DashboardPage.resolved24hColumnHeader'),
        value: sumQueues(queues, 'resolved_24h'),
      },
      {
        stage: t('DashboardPage.closed24hColumnHeader'),
        value: sumQueues(queues, 'closed_24h'),
      },
    ],
    [queues, t],
  )

  return (
    <BarChart
      height={220}
      dataset={dataset}
      xAxis={[{ dataKey: 'stage', scaleType: 'band' }]}
      series={[{ dataKey: 'value', label: t('DashboardPage.queueFlowSeriesLabel') }]}
    />
  )
}

const QUEUE_STAGE_BAR_WIDTH = 96

/** Compact per-queue stacked bar: waiting/picked/active proportioned by
 * count. Purely a faster-to-scan second encoding of the same numbers in
 * the columns to its right — the `role="img"`+`aria-label` pair carries
 * the full breakdown for assistive tech, since the colored segments alone
 * convey nothing without sight. */
function QueueStageBar({ queue, t }: { queue: LiveQueueDepth; t: TFunction }) {
  if (queue.open_conversations === 0) {
    return (
      <Box
        role="img"
        aria-label={t('DashboardPage.noOpenConversations')}
        sx={{
          width: QUEUE_STAGE_BAR_WIDTH,
          height: 8,
          borderRadius: 4,
          bgcolor: 'action.disabledBackground',
        }}
      />
    )
  }

  const segments = [
    { key: 'waiting', value: queue.waiting_count, color: 'warning.main' },
    { key: 'picked', value: queue.picked_count, color: 'info.main' },
    { key: 'active', value: queue.active_count, color: 'success.main' },
  ] as const

  const label = t('DashboardPage.queueFlowBarTooltip', {
    waiting: queue.waiting_count,
    picked: queue.picked_count,
    active: queue.active_count,
  })

  return (
    <Tooltip title={label}>
      <Stack
        direction="row"
        role="img"
        aria-label={label}
        sx={{ width: QUEUE_STAGE_BAR_WIDTH, height: 8, borderRadius: 4, overflow: 'hidden' }}
      >
        {segments.map(
          (segment) =>
            segment.value > 0 && (
              <Box key={segment.key} sx={{ flexGrow: segment.value, bgcolor: segment.color }} />
            ),
        )}
      </Stack>
    </Tooltip>
  )
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

/** Two-row grouped header: "Pipeline" (currently in the queue) and "Last
 * 24h" (throughput out of it) are visually distinct groups, so a
 * supervisor scanning the table doesn't mistake a resolved/closed count
 * for part of what's still waiting. */
function QueueDepthTable({ queues }: { queues: LiveQueueDepth[] }) {
  const { t } = useTranslation('dashboard')
  return (
    <TableContainer>
      <Table size="small" aria-label={t('DashboardPage.queueDepthHeading')}>
        <TableHead>
          <TableRow>
            <TableCell rowSpan={2}>{t('DashboardPage.queueColumnHeader')}</TableCell>
            <TableCell rowSpan={2}>{t('DashboardPage.departmentColumnHeader')}</TableCell>
            <TableCell rowSpan={2}>{t('DashboardPage.flowColumnHeader')}</TableCell>
            <TableCell align="center" colSpan={3}>
              {t('DashboardPage.pipelineGroupHeader')}
            </TableCell>
            <TableCell align="center" colSpan={2}>
              {t('DashboardPage.last24hGroupHeader')}
            </TableCell>
            <TableCell align="center" colSpan={2}>
              {t('DashboardPage.waitTimesGroupHeader')}
            </TableCell>
            <TableCell rowSpan={2} align="right">
              {t('DashboardPage.slaBreachedColumnHeader')}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell align="right">{t('DashboardPage.waitingColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.pickedColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.activeColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.resolved24hColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.closed24hColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.avgWaitColumnHeader')}</TableCell>
            <TableCell align="right">{t('DashboardPage.longestWaitingColumnHeader')}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {queues.map((queue) => (
            <TableRow key={queue.queue_id}>
              <TableCell>{queue.queue_name}</TableCell>
              <TableCell>{queue.department_name ?? t('DashboardPage.dashPlaceholder')}</TableCell>
              <TableCell>
                <Stack spacing={0.5} sx={{ alignItems: 'flex-start' }}>
                  <Chip label={queue.open_conversations} size="small" color="primary" />
                  <QueueStageBar queue={queue} t={t} />
                </Stack>
              </TableCell>
              <TableCell align="right">
                {queue.waiting_count > 0 ? (
                  <Chip label={queue.waiting_count} size="small" color="warning" />
                ) : (
                  queue.waiting_count
                )}
              </TableCell>
              <TableCell align="right">{queue.picked_count}</TableCell>
              <TableCell align="right">{queue.active_count}</TableCell>
              <TableCell align="right">{queue.resolved_24h}</TableCell>
              <TableCell align="right">{queue.closed_24h}</TableCell>
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
  const { hasPermission } = usePermissions()
  const canViewReports = hasPermission('reports.read')
  // Dashboard is the one nav item every authenticated user sees (it's
  // the post-login landing page, see LoginPage.tsx) — unlike every other
  // item, which is hidden entirely for a role that lacks its permission.
  // A custom role built in Roles & Permissions (e.g. chat-only,
  // knowledge-only) can omit reports.read, so this can't 403 the way the
  // query itself would: it has to degrade to a working landing page
  // instead, or that role would sign in to a broken first screen.
  const liveDashboardQuery = useLiveDashboardQuery({ enabled: canViewReports })

  return (
    <>
      <PageHeader title={t('DashboardPage.title')} description={t('DashboardPage.description')} />

      {!canViewReports && (
        <EmptyState
          title={t('DashboardPage.noReportsAccessTitle')}
          description={t('DashboardPage.noReportsAccessDescription')}
          action={
            <Button component={RouterLink} to="/conversations" variant="contained" size="small">
              {t('DashboardPage.goToInboxButton')}
            </Button>
          }
        />
      )}

      {canViewReports && liveDashboardQuery.isPending && (
        <LoadingState label={t('DashboardPage.loadingLabel')} />
      )}

      {canViewReports && liveDashboardQuery.isError && (
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
            label={t('DashboardPage.slaBreachedLabel')}
            value={liveDashboardQuery.data.conversations.sla_breached}
            alertWhenNonZero
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

          {liveDashboardQuery.data.queues.length > 0 && (
            <Grid size={12}>
              <Card variant="outlined">
                <CardContent>
                  <Typography
                    variant="subtitle1"
                    component="h3"
                    sx={{ fontWeight: 600 }}
                    gutterBottom
                  >
                    {t('DashboardPage.queueFlowHeading')}
                  </Typography>
                  <QueueFlowChart queues={liveDashboardQuery.data.queues} t={t} />
                </CardContent>
              </Card>
            </Grid>
          )}

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
