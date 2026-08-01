import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import { useSchedulerHealthQuery } from './api'
import type { SchedulerTaskHealth } from './types'

const HEALTH_COLOUR: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  healthy: 'success',
  degraded: 'warning',
  failing: 'error',
  never_run: 'default',
}

function when(value: string | null): string | null {
  if (!value) return null
  return new Date(value).toLocaleString()
}

/** Relative, because "40 minutes ago" answers "is this working?" and a
 * timestamp makes the reader do the arithmetic. */
function ago(value: string | null, t: TFunction<'platform'>): string {
  if (!value) return t('scheduler.never')
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000)
  if (minutes < 1) return t('scheduler.justNow')
  if (minutes < 60) return t('scheduler.minutesAgo', { count: minutes })
  const hours = Math.round(minutes / 60)
  if (hours < 48) return t('scheduler.hoursAgo', { count: hours })
  return t('scheduler.daysAgo', { count: Math.round(hours / 24) })
}

function TaskCard({ task }: { task: SchedulerTaskHealth }) {
  const { t } = useTranslation('platform')
  const run = task.last_run
  const failing = task.health === 'failing'

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {task.label}
          </Typography>
          <Chip
            size="small"
            color={HEALTH_COLOUR[task.health] ?? 'default'}
            label={t(`scheduler.health.${task.health}`)}
          />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {task.description}
        </Typography>

        {/* The question this page exists to answer. Every billing job is
            safe to repeat, so a single failure is survivable and invisible —
            what matters is whether it has succeeded *recently*. */}
        <Stack direction="row" spacing={4} sx={{ mt: 2, flexWrap: 'wrap' }}>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {t('scheduler.lastSuccess')}
            </Typography>
            <Typography variant="body2">{ago(task.last_success?.started_at ?? null, t)}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {t('scheduler.nextRun')}
            </Typography>
            <Typography variant="body2">{when(task.next_run_at) ?? '—'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {t('scheduler.duration')}
            </Typography>
            <Typography variant="body2">
              {run?.duration_ms != null ? t('scheduler.ms', { count: run.duration_ms }) : '—'}
            </Typography>
          </Box>
          {task.consecutive_failures > 0 ? (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                {t('scheduler.consecutiveFailures')}
              </Typography>
              <Typography variant="body2" color="error">
                {task.consecutive_failures}
              </Typography>
            </Box>
          ) : null}
          {run && run.attempt > 0 ? (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                {t('scheduler.retry')}
              </Typography>
              <Typography variant="body2">
                {t('scheduler.attemptNumber', { count: run.attempt + 1 })}
              </Typography>
            </Box>
          ) : null}
        </Stack>

        {run && run.metrics.length > 0 ? (
          <>
            <Divider sx={{ my: 2 }} />
            <Stack direction="row" spacing={4} sx={{ flexWrap: 'wrap' }}>
              {run.metrics.map((metric) => (
                <Box key={metric.key}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                    {metric.label}
                  </Typography>
                  <Typography variant="body2">{metric.value}</Typography>
                </Box>
              ))}
            </Stack>
          </>
        ) : null}

        {/* Items the run could not process. Shown even on a successful run:
            thirty companies billed and one not is a real problem that the
            word "succeeded" would otherwise hide. */}
        {run && run.failures > 0 ? (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {t('scheduler.itemsFailed', { count: run.failures })}
          </Alert>
        ) : null}

        {failing && run?.error ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {run.error}
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function PlatformHealthPage() {
  const { t } = useTranslation('platform')
  // Polled, because this page is left open on a wall and a stale "healthy"
  // is the one reading nobody should ever get.
  const query = useSchedulerHealthQuery()

  if (query.isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
        <CircularProgress />
      </Box>
    )
  }
  if (query.isError || !query.data) {
    return <Alert severity="error">{t('scheduler.loadFailed')}</Alert>
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>
            {t('scheduler.title')}
          </Typography>
          <Chip
            color={HEALTH_COLOUR[query.data.health] ?? 'default'}
            label={t(`scheduler.health.${query.data.health}`)}
          />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {t('scheduler.subtitle')}
        </Typography>
      </Box>

      {query.data.health === 'never_run' ? (
        <Alert severity="info">{t('scheduler.neverRunHint')}</Alert>
      ) : null}

      {query.data.tasks.map((task) => (
        <TaskCard key={task.name} task={task} />
      ))}

      <Typography variant="caption" color="text.secondary">
        {t('scheduler.evaluatedAt', { at: when(query.data.evaluated_at) })}
      </Typography>
    </Stack>
  )
}
