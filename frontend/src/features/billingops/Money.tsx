import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { formatAmount, formatCount } from './format'
import type { BillingStatus, InvoiceStatus } from './types'

/**
 * An amount, rendered at the currency's own resolution.
 *
 * The unrounded string the server sent stays in the tooltip. On a figure like
 * a unit rate the difference between `0.05` and `0.0512` is the difference
 * between two prices, and an operator quoting one to a customer should be
 * able to see exactly what was stored.
 *
 * `tabular-nums` throughout: a column of amounts that do not line up is a
 * column nobody can scan for the odd one out.
 */
export function Amount({
  value,
  currency,
  bold,
  colour,
}: {
  value: string | null | undefined
  currency: string
  bold?: boolean
  colour?: 'inherit' | 'text.secondary' | 'error.main' | 'success.main' | 'warning.main'
}) {
  const { i18n } = useTranslation()
  const rendered = formatAmount(value, currency, i18n.language)
  const exact = value ?? ''
  const body = (
    <Box
      component="span"
      sx={{
        fontVariantNumeric: 'tabular-nums',
        fontWeight: bold ? 600 : undefined,
        color: colour,
        whiteSpace: 'nowrap',
      }}
    >
      {rendered}
    </Box>
  )
  if (!exact || rendered === exact) return body
  return (
    <Tooltip title={`${exact} ${currency}`} disableInteractive>
      {body}
    </Tooltip>
  )
}

/** A count, aligned with the amounts beside it. */
export function Count({ value }: { value: number }) {
  const { i18n } = useTranslation()
  return (
    <Box component="span" sx={{ fontVariantNumeric: 'tabular-nums' }}>
      {formatCount(value, i18n.language)}
    </Box>
  )
}

/**
 * One figure with its label, as a finance report states it.
 *
 * The caption is not decoration — a number on a tile is worth exactly what
 * the reader knows about it, and "outstanding" and "billed this period"
 * answer different questions from the same ledger.
 */
export function Figure({
  label,
  value,
  caption,
  emphasis,
}: {
  label: string
  value: React.ReactNode
  caption?: string
  emphasis?: boolean
}) {
  return (
    <Stack spacing={0.25} sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: 0.4 }}>
        {label}
      </Typography>
      <Typography
        variant={emphasis ? 'h5' : 'h6'}
        component="p"
        sx={{ fontWeight: emphasis ? 700 : 600, fontVariantNumeric: 'tabular-nums' }}
      >
        {value}
      </Typography>
      {caption && (
        <Typography variant="caption" color="text.secondary">
          {caption}
        </Typography>
      )}
    </Stack>
  )
}

const INVOICE_COLOURS: Record<InvoiceStatus, 'default' | 'info' | 'success' | 'error' | 'warning'> =
  {
    draft: 'default',
    issued: 'info',
    paid: 'success',
    overdue: 'error',
    cancelled: 'warning',
  }

export function InvoiceStatusChip({ status }: { status: InvoiceStatus }) {
  const { t } = useTranslation('billingOps')
  return (
    <Chip
      size="small"
      variant={status === 'draft' ? 'outlined' : 'filled'}
      color={INVOICE_COLOURS[status]}
      label={t(`invoiceStatus.${status}`)}
    />
  )
}

const STANDING_COLOURS: Record<BillingStatus, 'success' | 'info' | 'warning' | 'error'> = {
  active: 'success',
  payment_due: 'info',
  payment_overdue: 'warning',
  payment_suspended: 'error',
}

export function StandingChip({ status }: { status: BillingStatus }) {
  const { t } = useTranslation('billingOps')
  return (
    <Chip
      size="small"
      variant={status === 'active' ? 'outlined' : 'filled'}
      color={STANDING_COLOURS[status]}
      label={t(`billingStatus.${status}`)}
    />
  )
}
