import { Card, CardContent, Divider, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatQuantity } from './money'
import type { BillingConfiguration } from './types'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{ justifyContent: 'space-between', alignItems: 'baseline' }}
    >
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ textAlign: 'end' }}>
        {value}
      </Typography>
    </Stack>
  )
}

/**
 * The rules this company is billed under.
 *
 * Shown because a bill cannot be sanity-checked without them, and because
 * being told the allowance was 100 conversations *after* exceeding it is not
 * the same as knowing beforehand. The suspension window comes from the same
 * dunning policy that actually suspends, so the two cannot disagree.
 */
export function BillingConfigurationCard({
  configuration,
}: {
  configuration: BillingConfiguration
}) {
  const { t, i18n } = useTranslation('billing')
  const allowances = Object.entries(configuration.free_monthly_allowance)

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600, mb: 1.5 }}>
          {t('configuration.title')}
        </Typography>
        <Stack spacing={1}>
          <Row
            label={t('configuration.model')}
            value={t('configuration.modelValue', { defaultValue: configuration.billing_model })}
          />
          <Row
            label={t('configuration.cadence')}
            value={t('configuration.cadenceValue', {
              defaultValue: configuration.invoice_cadence,
            })}
          />
          <Row
            label={t('configuration.terms')}
            value={t('configuration.termsValue', { days: configuration.payment_terms_days })}
          />
          <Row
            label={t('configuration.currency')}
            value={`${configuration.currency} (${configuration.currency_symbol})`}
          />
          <Row
            label={t('configuration.country')}
            value={configuration.country_name ?? t('configuration.countryUnknown')}
          />
          <Row
            label={t('configuration.autoSuspend')}
            value={
              configuration.auto_suspend_enabled && configuration.suspend_after_days !== null
                ? t('configuration.autoSuspendValue', { days: configuration.suspend_after_days })
                : t('configuration.autoSuspendDisabled')
            }
          />
        </Stack>

        {allowances.length > 0 ? (
          <>
            <Divider sx={{ my: 1.5 }} />
            <Typography variant="caption" color="text.secondary">
              {t('configuration.allowanceTitle')}
            </Typography>
            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
              {allowances.map(([metric, quantity]) => (
                <Row
                  key={metric}
                  label={t(`metric.${metric}`, { defaultValue: metric })}
                  value={t('configuration.allowanceValue', {
                    quantity: formatQuantity(quantity, i18n.language),
                  })}
                />
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              {t('configuration.allowanceHint')}
            </Typography>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
