import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router-dom'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import LinearProgress from '@mui/material/LinearProgress'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import { useRevenueQuery } from './api'
import { formatDay, formatMoment, formatRatio, windowOfDays } from './format'
import { Amount, Figure } from './Money'
import type { CurrencyRevenue } from './types'

const WINDOWS = [30, 60, 90] as const
type WindowDays = (typeof WINDOWS)[number]

/**
 * The run rate, with the method it was derived by — never without.
 *
 * Blink Engage bills for usage and sells no subscriptions, so there is no
 * contracted recurring revenue to report. This figure is recognised revenue
 * scaled to thirty days, and it says so, because a derived number quoted
 * without its derivation is one nobody can defend in a board meeting.
 */
function RunRate({ row }: { row: CurrencyRevenue }) {
  const { t } = useTranslation('billingOps')
  const { run_rate: rate } = row

  if (!rate.is_meaningful) {
    return (
      <Figure
        label={t('revenue.runRate')}
        value={
          <Typography variant="h6" component="span" color="text.secondary">
            {t('revenue.runRateUnavailable')}
          </Typography>
        }
        caption={t('revenue.runRateNeedsMoreHistory', { days: rate.days_observed })}
      />
    )
  }
  // The caption is the method, in words. The two are genuinely different
  // claims: a thirty-day window *is* the monthly figure, while any other
  // window was scaled to look like one — steadier from ninety days, jumpier
  // from ten. `days_observed` is what tells the reader which they are
  // holding, so it travels with both.
  return (
    <Figure
      label={t('revenue.runRate')}
      value={<Amount value={rate.amount} currency={rate.currency} bold />}
      caption={
        rate.method === 'trailing_30_day'
          ? t('revenue.runRateTrailing')
          : t('revenue.runRateScaled', { days: rate.days_observed })
      }
    />
  )
}

/**
 * One currency's position.
 *
 * A card per currency rather than columns in one table, because these do not
 * belong on the same row: nothing converts between dollars and dinars, no
 * exchange rate is stored anywhere on purpose, and a layout that invited the
 * eye to add them across would be inviting a number that means nothing.
 */
function CurrencyCard({ row }: { row: CurrencyRevenue }) {
  const { t, i18n } = useTranslation('billingOps')
  const ratio = row.collection_ratio === null ? null : Number(row.collection_ratio)

  return (
    <Card variant="outlined" sx={{ flex: '1 1 340px', minWidth: 320 }}>
      <CardContent>
        <Stack
          direction="row"
          sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2 }}
        >
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {t('revenue.booksIn', { currency: row.currency })}
          </Typography>
          <Chip size="small" variant="outlined" label={row.currency} />
        </Stack>

        <Stack direction="row" spacing={3} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
          <Figure
            label={t('revenue.recognised')}
            value={<Amount value={row.revenue} currency={row.currency} />}
            caption={t('revenue.recognisedCaption')}
            emphasis
          />
          <RunRate row={row} />
        </Stack>

        <Divider sx={{ my: 2 }} />

        {/* A grid rather than a wrapping row: with four figures and a card
            that narrows, `flexWrap` leaves the odd one out hanging under the
            first column with a stray indent. Columns that share a width read
            as a set, which is what these four are. */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            columnGap: 3,
            rowGap: 2,
          }}
        >
          <Figure
            label={t('revenue.collected')}
            value={<Amount value={row.collected} currency={row.currency} />}
            caption={t('revenue.collectedCaption')}
          />
          <Figure
            label={t('revenue.outstanding')}
            value={
              <Amount
                value={row.outstanding}
                currency={row.currency}
                colour={Number(row.outstanding) > 0 ? 'warning.main' : undefined}
              />
            }
            caption={t('revenue.outstandingCaption')}
          />
          <Figure
            label={t('revenue.customerCredit')}
            value={<Amount value={row.customer_credit} currency={row.currency} />}
            caption={t('revenue.customerCreditCaption')}
          />
          <Figure
            label={t('revenue.badDebt')}
            value={
              <Amount
                value={row.bad_debt}
                currency={row.currency}
                colour={Number(row.bad_debt) > 0 ? 'error.main' : undefined}
              />
            }
            caption={t('revenue.badDebtCaption')}
          />
        </Box>

        <Box sx={{ mt: 2.5 }}>
          <Stack
            direction="row"
            sx={{ alignItems: 'baseline', justifyContent: 'space-between', mb: 0.5 }}
          >
            <Typography variant="caption" color="text.secondary">
              {t('revenue.collectionRatio')}
            </Typography>
            <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatRatio(row.collection_ratio, i18n.language)}
            </Typography>
          </Stack>
          {/* No bar at all when there is no ratio. An empty track reads as
              "nothing collected", which is a different and much worse claim
              than "nothing was billed, so there is nothing to measure".

              When there is one, the bar is capped at full but the figure
              above it is not: a window that collected arrears billed before
              it really did collect more than it billed, and the percentage
              says so even though a progress bar has nowhere to show it. */}
          {ratio !== null && (
            <Tooltip
              title={ratio > 1 ? t('revenue.collectionRatioOver') : ''}
              disableInteractive
            >
              <LinearProgress
                variant="determinate"
                value={Math.min(ratio, 1) * 100}
                color={ratio >= 0.9 ? 'success' : 'primary'}
                sx={{ height: 6, borderRadius: 3 }}
              />
            </Tooltip>
          )}
          <Typography variant="caption" color="text.secondary">
            {row.collection_ratio === null
              ? t('revenue.collectionRatioUndefined')
              : t('revenue.collectionRatioCaption')}
          </Typography>
        </Box>
      </CardContent>
    </Card>
  )
}

/**
 * The Billing Console's front page.
 *
 * Opens on the numbers rather than on a settings form, which is the whole
 * difference between a finance module and a preferences page.
 */
export function RevenueDashboardPage() {
  const { t, i18n } = useTranslation('billingOps')
  const [days, setDays] = useState<WindowDays>(30)
  const query = useRevenueQuery(windowOfDays(days))

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}
      >
        <Box>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
            {t('revenue.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {query.data
              ? t('revenue.period', {
                  from: formatDay(query.data.period_from, i18n.language),
                  to: formatDay(query.data.period_to, i18n.language),
                })
              : t('revenue.subtitle')}
          </Typography>
        </Box>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={days}
          onChange={(_, next) => next && setDays(next as WindowDays)}
          aria-label={t('revenue.windowLabel')}
        >
          {WINDOWS.map((option) => (
            <ToggleButton key={option} value={option}>
              {t('revenue.windowDays', { days: option })}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      </Stack>

      {query.isError && <Alert severity="error">{t('revenue.loadFailed')}</Alert>}

      {query.isLoading && (
        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
          <Skeleton variant="rounded" height={280} sx={{ flex: '1 1 340px' }} />
          <Skeleton variant="rounded" height={280} sx={{ flex: '1 1 340px' }} />
        </Stack>
      )}

      {query.data && (
        <>
          <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
            {query.data.currencies.map((row) => (
              <CurrencyCard key={row.currency} row={row} />
            ))}
            {query.data.currencies.length === 0 && (
              <Alert severity="info" sx={{ flex: 1 }}>
                {t('revenue.noBooks')}
              </Alert>
            )}
          </Stack>

          <Card variant="outlined">
            <CardContent>
              <Stack
                direction="row"
                spacing={4}
                sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 2 }}
              >
                <Figure
                  label={t('revenue.companiesBehind')}
                  value={query.data.companies_behind}
                  caption={t('revenue.companiesBehindCaption')}
                />
                <Figure
                  label={t('revenue.companiesSuspended')}
                  value={query.data.companies_suspended}
                  caption={t('revenue.companiesSuspendedCaption')}
                />
                <Box sx={{ flexGrow: 1 }} />
                <Button
                  component={RouterLink}
                  to="/platform/billing/collections"
                  variant="outlined"
                  size="small"
                >
                  {t('revenue.openCollections')}
                </Button>
              </Stack>
            </CardContent>
          </Card>

          {/* Said out loud rather than implied. Collections and the daily
              aggregates sweep on a schedule, so a console that looked
              real-time would be lying by omission. */}
          <Typography variant="caption" color="text.secondary">
            {t('revenue.asOf', { moment: formatMoment(query.data.as_of, i18n.language) })}
          </Typography>
        </>
      )}
    </Stack>
  )
}
