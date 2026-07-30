import { Alert, AlertTitle, Box, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { BillingOverview } from './types'

/** Severity per status. Suspension is an error because it is one; "payment
 * due" is information, not a problem — a customer who pays on time should
 * never see a warning colour for behaving correctly. */
const SEVERITY = {
  active: 'success',
  payment_due: 'info',
  payment_overdue: 'warning',
  payment_suspended: 'error',
} as const

/**
 * "Whether I need to take action" — one of the five questions the page must
 * answer within ten seconds, so it sits at the top and states the action in
 * words rather than encoding it in a colour.
 *
 * The sentence comes from the API. Written once, server-side, so the
 * dashboard, the reminder emails and the operator console cannot describe the
 * same situation differently — and so the suspension date comes from the
 * dunning policy instead of being retyped here.
 */
export function BillingStatusBanner({ overview }: { overview: BillingOverview }) {
  const { t } = useTranslation('billing')
  const severity = SEVERITY[overview.billing_status]

  return (
    <Alert severity={severity} sx={{ mb: 3 }} data-testid="billing-status">
      <AlertTitle sx={{ mb: 0.5 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Box component="span">{t(`status.${overview.billing_status}`)}</Box>
          <Chip
            size="small"
            variant="outlined"
            label={t('status.currencyChip', { currency: overview.currency })}
          />
        </Stack>
      </AlertTitle>
      <Typography variant="body2">
        {/* Translated from the code, with the server's English sentence as the
            fallback. The wording is composed once, server-side, so the
            dashboard, the reminder emails and the operator console cannot
            describe the same situation differently — but a customer still has
            to be able to read it in their own language, and a code this build
            has never heard of must not blank the banner. */}
        {t(`statusDetail.${overview.status_detail_code}`, {
          ...overview.status_detail_params,
          defaultValue: overview.status_detail,
        })}
      </Typography>
    </Alert>
  )
}
