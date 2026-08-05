import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Slider,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useLearningThresholds, useUpdateThresholds } from './api'

/** The one control on this screen that changes what the platform finds.
 *
 * Sliders bounded by the values the backend will accept, because a
 * control that can express a refused value teaches the operator to
 * distrust the form. The bounds are not cosmetic: outside them clustering
 * either conflates distinct problems into one finding or fragments one
 * problem into invisibility, both measured — see the shadow validation
 * report.
 *
 * A reason field, because six months later "why did the platform stop
 * finding anything in March?" is answered by the audit row, and a row
 * with no reason only says that somebody changed a number.
 */
export function ThresholdPanel({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation('intelligence')
  const { data } = useLearningThresholds()
  const update = useUpdateThresholds()
  const [join, setJoin] = useState<number | null>(null)
  const [reason, setReason] = useState('')

  if (!data) return null

  const bounds = data.bounds.cluster_join_threshold ?? { min: 0.05, max: 0.6 }
  const current = data.thresholds.cluster_join_threshold ?? bounds.min
  const pending = join ?? current
  const dirty = Math.abs(pending - current) > 1e-9

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2">{t('Thresholds.title')}</Typography>
          {data.overridden.includes('cluster_join_threshold') ? (
            <Chip size="small" label={t('Thresholds.overridden')} />
          ) : (
            <Chip size="small" variant="outlined" label={t('Thresholds.inherited')} />
          )}
        </Stack>

        <Typography variant="body2" color="text.secondary" gutterBottom>
          {t('Thresholds.joinDescription')}
        </Typography>

        <Box sx={{ px: 1, pt: 2 }}>
          <Slider
            value={pending}
            min={bounds.min}
            max={bounds.max}
            step={0.01}
            marks={[
              { value: bounds.min, label: String(bounds.min) },
              { value: current, label: t('Thresholds.currentMark') },
              { value: bounds.max, label: String(bounds.max) },
            ]}
            valueLabelDisplay="auto"
            disabled={!canManage}
            onChange={(_, value) => setJoin(value as number)}
            aria-label={t('Thresholds.joinAriaLabel')}
          />
        </Box>

        {dirty ? (
          <Alert severity="warning" sx={{ mt: 1 }}>
            {t('Thresholds.invalidationWarning')}
          </Alert>
        ) : null}

        {canManage ? (
          <Stack direction="row" spacing={1} sx={{ mt: 2, alignItems: 'flex-start' }}>
            <TextField
              size="small"
              fullWidth
              label={t('Thresholds.reasonLabel')}
              helperText={t('Thresholds.reasonHelp')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <Button
              variant="contained"
              disabled={!dirty || update.isPending}
              onClick={() =>
                update.mutate(
                  { cluster_join_threshold: pending, reason: reason || undefined },
                  { onSuccess: () => { setJoin(null); setReason('') } },
                )
              }
            >
              {t('Thresholds.save')}
            </Button>
          </Stack>
        ) : null}

        {update.isError ? (
          <Alert severity="error" sx={{ mt: 1 }}>
            {t('Thresholds.saveFailed')}
          </Alert>
        ) : null}
        {update.isSuccess && update.data.changes.length > 0 ? (
          <Alert severity="success" sx={{ mt: 1 }}>
            {t('Thresholds.saved', {
              count: update.data.clusters_built_under_previous_thresholds,
            })}
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}
