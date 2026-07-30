import {
  Alert,
  Card,
  CardContent,
  Chip,
  Divider,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatEstimate, type CurrencyFormat } from './money'
import { projectionExplanation, projectionMethod, projectionUnavailable } from './projectionText'
import type { Projection, ProjectionStrategy } from './types'

const STRATEGIES: ProjectionStrategy[] = ['rolling_7_day', 'daily_average', 'linear_pace']

/**
 * What this month is heading for, and how that was worked out.
 *
 * Three things are deliberate. The **method is stated on the face of the
 * card**, not in a tooltip — a projection whose derivation is hidden is a
 * number a customer can neither check nor challenge. A **fallback is
 * announced**: when fewer than seven complete days exist, the rolling average
 * cannot run, and saying "Rolling 7-Day" anyway would be a small lie that
 * costs a lot of trust when noticed. And the **other strategies are shown**,
 * because seeing three reasonable models land on three nearby numbers
 * communicates that this is an estimate far better than any disclaimer.
 */
export function ProjectionCard({
  projection,
  alternatives,
  format,
  strategy,
  defaultStrategy,
  onStrategyChange,
}: {
  projection: Projection
  alternatives: Projection[]
  format: CurrencyFormat
  strategy: ProjectionStrategy | null
  defaultStrategy: ProjectionStrategy
  onStrategyChange: (strategy: ProjectionStrategy | null) => void
}) {
  const { t, i18n } = useTranslation('billing')
  const method = projectionMethod(projection, t)

  return (
    <Card variant="outlined" sx={{ height: '100%' }} data-testid="projection-card">
      <CardContent>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          sx={{ justifyContent: 'space-between', alignItems: { sm: 'flex-start' }, mb: 1 }}
        >
          <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
            {t('projection.title')}
          </Typography>
          <TextField
            select
            size="small"
            label={t('projection.methodLabel')}
            value={strategy ?? defaultStrategy}
            onChange={(event) => {
              const next = event.target.value as ProjectionStrategy
              onStrategyChange(next === defaultStrategy ? null : next)
            }}
            sx={{ minWidth: 220 }}
          >
            {STRATEGIES.map((option) => (
              <MenuItem key={option} value={option}>
                {t(`projection.strategy.${option}`)}
                {option === defaultStrategy ? ` — ${t('projection.defaultSuffix')}` : ''}
              </MenuItem>
            ))}
          </TextField>
        </Stack>

        {projection.projected_total === null ? (
          <Alert severity="info" sx={{ mb: 2 }}>
            {projectionUnavailable(projection, t) || t('projection.unavailable')}
          </Alert>
        ) : (
          <>
            <Typography
              variant="h4"
              component="p"
              sx={{ fontVariantNumeric: 'tabular-nums' }}
              data-testid="projected-total"
            >
              {formatEstimate(projection.projected_total, format, i18n.language)}
            </Typography>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: 'center', flexWrap: 'wrap', mt: 1 }}
            >
              <Chip
                size="small"
                color={projection.fell_back ? 'warning' : 'default'}
                label={t('projection.methodChip', { method })}
              />
              <Typography variant="caption" color="text.secondary">
                {t('projection.daysMeasured', {
                  measured: projection.days_measured,
                  elapsed: projection.days_elapsed,
                  total: projection.days_in_period,
                })}
              </Typography>
            </Stack>
            {projection.fell_back ? (
              <Alert severity="info" sx={{ mt: 2 }} data-testid="projection-fallback">
                {t('projection.fellBackDetail', {
                  requested: t(`projection.strategy.${projection.strategy}`),
                  used: method,
                })}
              </Alert>
            ) : null}
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              {projectionExplanation(projection, t)}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {t('projection.actualToDate', {
                actual: formatEstimate(projection.actual_to_date, format, i18n.language),
                average: formatEstimate(projection.daily_average, format, i18n.language),
              })}
            </Typography>
          </>
        )}

        {alternatives.length > 0 ? (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="caption" color="text.secondary">
              {t('projection.alternativesTitle')}
            </Typography>
            <Stack spacing={0.5} sx={{ mt: 1 }}>
              {alternatives.map((alternative) => (
                <Stack
                  key={alternative.strategy}
                  direction="row"
                  spacing={1}
                  sx={{ justifyContent: 'space-between' }}
                >
                  <Typography variant="body2" color="text.secondary">
                    {projectionMethod(alternative, t)}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ fontVariantNumeric: 'tabular-nums' }}
                    color={alternative.projected_total === null ? 'text.disabled' : 'text.primary'}
                  >
                    {alternative.projected_total === null
                      ? t('projection.notAvailableShort')
                      : formatEstimate(alternative.projected_total, format, i18n.language)}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </>
        ) : null}

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          {t('projection.estimateDisclaimer')}
        </Typography>
      </CardContent>
    </Card>
  )
}
