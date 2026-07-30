import { useMemo } from 'react'
import {
  Box,
  Card,
  CardContent,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { useTranslation } from 'react-i18next'
import { formatDay, formatDayShort, formatEstimate, type CurrencyFormat } from './money'
import type { ChartWindow, DailySeries } from './types'

const WINDOWS: ChartWindow[] = ['7d', '30d', 'period']

/**
 * Daily estimated cost, from the immutable daily aggregates.
 *
 * Two series rather than one: days that have closed and today, which is still
 * moving. Rendering them identically would show a bar that grows every time
 * the page refreshes and give no clue why — and a customer comparing today's
 * partial bar against yesterday's full one is being invited to a wrong
 * conclusion.
 */
export function DailyCostChart({
  series,
  format,
  window,
  onWindowChange,
  loading = false,
}: {
  series: DailySeries
  format: CurrencyFormat
  window: ChartWindow
  onWindowChange: (window: ChartWindow) => void
  loading?: boolean
}) {
  const { t, i18n } = useTranslation('billing')

  const dataset = useMemo(
    () =>
      series.days.map((day) => ({
        day: formatDayShort(day.day, i18n.language),
        iso: day.day,
        // Split into two keys so the open day can be styled differently. A
        // closed day contributes 0 to the open series and vice versa, so the
        // bars still line up on one axis.
        closed: day.final ? Number(day.estimated_cost) : 0,
        open: day.final ? 0 : Number(day.estimated_cost),
      })),
    [series.days, i18n.language],
  )

  const hasAnyCost = series.days.some((day) => Number(day.estimated_cost) > 0)

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' }, mb: 2 }}
        >
          <Box>
            <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
              {t('chart.title')}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('chart.subtitle', {
                total: formatEstimate(series.total_estimated_cost, format, i18n.language),
                start: formatDay(series.start, i18n.language),
                end: formatDay(series.end, i18n.language),
              })}
            </Typography>
          </Box>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={window}
            onChange={(_event, next) => {
              // MUI emits null when the active button is clicked again;
              // switching to "no window" would blank the chart.
              if (next) onWindowChange(next as ChartWindow)
            }}
            aria-label={t('chart.windowAriaLabel')}
          >
            {WINDOWS.map((option) => (
              <ToggleButton key={option} value={option} disabled={loading}>
                {t(`chart.window.${option}`)}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>

        {hasAnyCost ? (
          <Box sx={{ width: '100%' }}>
            <BarChart
              height={280}
              dataset={dataset}
              xAxis={[{ dataKey: 'day', scaleType: 'band' }]}
              yAxis={[{ width: 72 }]}
              series={[
                {
                  dataKey: 'closed',
                  label: t('chart.finalSeries'),
                  stack: 'cost',
                  valueFormatter: (value: number | null) =>
                    value === null || value === 0
                      ? ''
                      : formatEstimate(String(value), format, i18n.language),
                },
                {
                  dataKey: 'open',
                  label: t('chart.openSeries'),
                  stack: 'cost',
                  valueFormatter: (value: number | null) =>
                    value === null || value === 0
                      ? ''
                      : formatEstimate(String(value), format, i18n.language),
                },
              ]}
            />
          </Box>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
            {t('chart.empty')}
          </Typography>
        )}

        {series.data_starts_on ? (
          // Without this, a 30-day chart on a company that signed up last
          // week draws three weeks of flat zero and implies no usage, when
          // the truth is that nothing was recorded yet.
          <Typography variant="caption" color="text.secondary">
            {t('chart.dataStartsOn', {
              date: formatDay(series.data_starts_on, i18n.language),
            })}
          </Typography>
        ) : null}
      </CardContent>
    </Card>
  )
}
