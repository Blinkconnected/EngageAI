import { Box, Card, CardContent, Stack, Tooltip, Typography } from '@mui/material'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useTranslation } from 'react-i18next'
import type { Measured } from './types'

/** One number, with the thing it cannot say marked as such.
 *
 * The `null` case is the reason this component exists rather than a bare
 * `<Typography>`. A pilot dashboard is read by somebody deciding whether
 * to trust the platform, and "—" with an explanation is a different
 * claim from "0". Rendering an unmeasurable metric as zero would report
 * churn on an installation whose clusters have simply not settled yet,
 * and the operator would act on it.
 */
export function MetricTile({
  label,
  value,
  suffix,
  hint,
  emphasis,
}: {
  label: string
  value: Measured | string
  suffix?: string
  hint?: string
  emphasis?: 'good' | 'warn' | 'none'
}) {
  const { t } = useTranslation('intelligence')
  const unmeasured = value === null || value === undefined
  const colour =
    emphasis === 'warn' ? 'warning.main' : emphasis === 'good' ? 'success.main' : 'text.primary'

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.4 }}>
            {label}
          </Typography>
          {hint ? (
            <Tooltip title={hint}>
              <InfoOutlinedIcon fontSize="inherit" sx={{ color: 'text.disabled' }} />
            </Tooltip>
          ) : null}
        </Stack>
        <Box sx={{ mt: 0.5 }}>
          {unmeasured ? (
            <Tooltip title={t('MetricTile.notMeasurableHint')}>
              <Typography variant="h5" color="text.disabled">
                {t('MetricTile.notMeasurable')}
              </Typography>
            </Tooltip>
          ) : (
            <Typography variant="h5" sx={{ color: colour }}>
              {typeof value === 'number' ? value.toLocaleString() : value}
              {suffix ? (
                <Typography component="span" variant="body2" color="text.secondary">
                  {' '}
                  {suffix}
                </Typography>
              ) : null}
            </Typography>
          )}
        </Box>
      </CardContent>
    </Card>
  )
}
