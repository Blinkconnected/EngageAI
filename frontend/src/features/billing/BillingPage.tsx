import { useState } from 'react'
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { useBillingDashboardQuery, useBillingEstimateQuery, useDailyCostQuery } from './api'
import { BillingConfigurationCard } from './BillingConfigurationCard'
import { BillingStatusBanner } from './BillingStatusBanner'
import { CostTransparencyCard } from './CostTransparencyCard'
import { DailyCostChart } from './DailyCostChart'
import { InvoiceHistoryPanel } from './InvoiceHistoryPanel'
import { InvoiceTimeline } from './InvoiceTimeline'
import { MetricCostTable } from './MetricCostTable'
import { OverviewCards } from './OverviewCards'
import { PaymentMethodsCard } from './PaymentMethodsCard'
import { ProjectionCard } from './ProjectionCard'
import { formatTime, type CurrencyFormat } from './money'
import type { ChartWindow, ProjectionStrategy } from './types'

/**
 * The billing dashboard — a financial control centre, not an accounting
 * screen.
 *
 * Ordered by the questions a customer arrives with, most urgent first: do I
 * need to do anything (the banner), what am I spending (the cards), where is
 * it going (today and month-to-date), where is it heading (the projection and
 * chart), what happens next (the timeline), and finally the official
 * documents. Anything a customer would only look up occasionally — payment
 * methods, rates, the rules — sits below that.
 *
 * The line between **estimates** and **issued invoices** is drawn once,
 * visibly, with a divider and its own heading. Everything above it is derived
 * from usage and labelled as an estimate; everything below is a document
 * somebody has issued.
 */
export function BillingPage() {
  const { t, i18n } = useTranslation('billing')
  const [window, setWindow] = useState<ChartWindow>('30d')
  const [strategy, setStrategy] = useState<ProjectionStrategy | null>(null)

  const dashboard = useBillingDashboardQuery()

  // Seeded from the dashboard response while the default method is showing, so
  // opening the page makes one request rather than two and the first poll
  // happens 45 seconds later. A method the customer picks has no seed and is
  // fetched — the server computes every projection, never this page.
  const estimate = useBillingEstimateQuery(strategy, {
    enabled: dashboard.data !== undefined,
    seed:
      strategy === null && dashboard.data
        ? { data: dashboard.data.estimate, at: dashboard.dataUpdatedAt }
        : undefined,
  })

  // The chart re-fetches on its own when the window changes, so switching
  // between 7 days and the period does not re-read invoices and pricing.
  const daily = useDailyCostQuery(window, dashboard.data !== undefined)

  if (dashboard.isPending) return <LoadingState label={t('page.loading')} />
  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
  }

  const data = dashboard.data
  const overview = data.overview
  const live = estimate.data ?? data.estimate
  const series = daily.data ?? data.daily
  const format: CurrencyFormat = {
    currency: overview.currency,
    decimals: overview.currency_decimal_places,
  }

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        sx={{ justifyContent: 'space-between', alignItems: { sm: 'baseline' }, mb: 1 }}
      >
        <Typography variant="h5" component="h1">
          {t('page.title')}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          {/* The page updates itself; saying so is what stops somebody
              reloading to check whether the number moved. */}
          <Chip
            size="small"
            variant="outlined"
            label={t('page.liveChip', { time: formatTime(live.as_of, i18n.language) })}
            data-testid="live-chip"
          />
        </Stack>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('page.subtitle')}
      </Typography>

      <BillingStatusBanner overview={overview} />

      {overview.no_open_period ? (
        <Alert severity="info" sx={{ mb: 3 }}>
          {t('page.noOpenPeriod')}
        </Alert>
      ) : null}

      <OverviewCards overview={overview} estimate={live} />

      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
              <Stack spacing={0.5} sx={{ mb: 1 }}>
                <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
                  {t('usage.todayTitle')}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('usage.todaySubtitle')}
                </Typography>
              </Stack>
              <MetricCostTable
                rows={live.today}
                format={format}
                emptyLabel={t('usage.todayEmpty')}
                ariaLabel={t('usage.todayTableAriaLabel')}
                dense
              />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <ProjectionCard
            projection={live.projection}
            // Whatever is being shown as the headline figure is not also an
            // "alternative" — the same number twice reads as a bug.
            alternatives={data.projection_alternatives.filter(
              (candidate) => candidate.strategy !== live.projection.strategy,
            )}
            format={format}
            strategy={strategy}
            defaultStrategy={data.configuration.projection_strategy_default}
            onStrategyChange={setStrategy}
          />
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ mt: 2 }}>
        <CardContent>
          <Stack spacing={0.5} sx={{ mb: 1 }}>
            <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
              {t('usage.periodTitle')}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('usage.periodSubtitle', {
                elapsed: overview.days_elapsed,
                total: overview.days_elapsed + overview.days_remaining,
              })}
            </Typography>
          </Stack>
          <MetricCostTable
            rows={live.month_to_date}
            format={format}
            emptyLabel={t('usage.periodEmpty')}
            ariaLabel={t('usage.periodTableAriaLabel')}
          />
        </CardContent>
      </Card>

      <Box sx={{ mt: 2 }}>
        <DailyCostChart
          series={series}
          format={format}
          window={window}
          onWindowChange={setWindow}
          loading={daily.isFetching}
        />
      </Box>

      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid size={{ xs: 12, md: 7 }}>
          <InvoiceTimeline
            events={data.timeline}
            paymentTermsDays={data.configuration.payment_terms_days}
            suspendAfterDays={data.configuration.suspend_after_days}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <PaymentMethodsCard methods={data.payment_methods} />
        </Grid>
      </Grid>

      {/* The one line on the page that must never blur: estimates above,
          issued documents below. */}
      <Divider sx={{ my: 4 }} />
      <Typography variant="h6" component="h2" sx={{ mb: 0.5 }}>
        {t('official.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('official.subtitle')}
      </Typography>

      <InvoiceHistoryPanel invoices={data.invoices} format={format} />

      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <CostTransparencyCard prices={data.unit_prices} format={format} />
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <BillingConfigurationCard configuration={data.configuration} />
        </Grid>
      </Grid>
    </Box>
  )
}
