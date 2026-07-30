import { Card, CardContent, Chip, Grid, Stack, Tooltip, Typography } from '@mui/material'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useTranslation } from 'react-i18next'
import { formatDay, formatEstimate, formatMoney, type CurrencyFormat } from './money'
import { projectionExplanation, projectionMethod } from './projectionText'
import type { BillingEstimate, BillingOverview } from './types'

function MetricCard({
  label,
  value,
  caption,
  chip,
  hint,
  testId,
}: {
  label: string
  value: string
  caption?: string
  chip?: string
  hint?: string
  testId?: string
}) {
  return (
    <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
      <Card variant="outlined" sx={{ height: '100%' }} data-testid={testId}>
        <CardContent>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', mb: 0.5 }}>
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            {hint ? (
              <Tooltip title={hint}>
                {/* A real button would be a tab stop on a decorative hint;
                    an icon with an accessible label is reachable by screen
                    readers without adding one. */}
                <InfoOutlinedIcon
                  fontSize="small"
                  color="disabled"
                  aria-label={hint}
                  role="img"
                  sx={{ fontSize: 16 }}
                />
              </Tooltip>
            ) : null}
          </Stack>
          <Typography variant="h5" component="p" sx={{ fontVariantNumeric: 'tabular-nums' }}>
            {value}
          </Typography>
          <Stack
            direction="row"
            spacing={1}
            sx={{ alignItems: 'center', mt: 0.5, flexWrap: 'wrap' }}
          >
            {caption ? (
              <Typography variant="caption" color="text.secondary">
                {caption}
              </Typography>
            ) : null}
            {chip ? <Chip size="small" label={chip} /> : null}
          </Stack>
        </CardContent>
      </Card>
    </Grid>
  )
}

/**
 * The four figures a customer wants first: today, this month, what the month
 * is heading for, and what is actually owed.
 *
 * The first three are **estimates** and are labelled so. The fourth comes
 * from the ledger and is what issued invoices say — the one number on this
 * row that is not a projection of anything.
 */
export function OverviewCards({
  overview,
  estimate,
}: {
  overview: BillingOverview
  estimate: BillingEstimate
}) {
  const { t, i18n } = useTranslation('billing')
  const format: CurrencyFormat = {
    currency: overview.currency,
    decimals: overview.currency_decimal_places,
  }
  const projection = estimate.projection

  return (
    <Grid container spacing={2}>
      <MetricCard
        testId="card-today"
        label={t('overview.today')}
        value={formatEstimate(estimate.estimated_today, format, i18n.language)}
        caption={t('overview.estimated')}
      />
      <MetricCard
        testId="card-mtd"
        label={t('overview.monthToDate')}
        value={formatEstimate(estimate.estimated_month_to_date, format, i18n.language)}
        caption={t('overview.periodRange', {
          start: formatDay(overview.period_start, i18n.language),
          end: formatDay(overview.period_last_day, i18n.language),
        })}
      />
      <MetricCard
        testId="card-projection"
        label={t('overview.projected')}
        value={
          projection.projected_total === null
            ? t('overview.notYetAvailable')
            : formatEstimate(projection.projected_total, format, i18n.language)
        }
        // The method travels with the number, always. A projection with no
        // stated method is not something a customer can check.
        caption={t('overview.projectionMethod', { method: projectionMethod(projection, t) })}
        chip={projection.fell_back ? t('projection.fellBackChip') : undefined}
        hint={projectionExplanation(projection, t)}
      />
      <MetricCard
        testId="card-outstanding"
        label={t('overview.outstanding')}
        value={formatMoney(overview.outstanding_balance, format, i18n.language)}
        caption={t('overview.outstandingCaption', {
          date: formatDay(overview.next_payment_due_on, i18n.language),
        })}
        chip={
          Number(overview.credit_balance) > 0
            ? t('overview.creditChip', {
                amount: formatMoney(overview.credit_balance, format, i18n.language),
              })
            : undefined
        }
      />
    </Grid>
  )
}
