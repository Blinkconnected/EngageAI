import { Fragment, useState } from 'react'
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import { useTranslation } from 'react-i18next'
import { useInvoiceDetailQuery } from './api'
import {
  formatDay,
  formatMoney,
  formatQuantity,
  formatUnitPrice,
  type CurrencyFormat,
} from './money'
import type { InvoiceStatus, InvoiceSummary } from './types'

const STATUS_COLOUR: Record<InvoiceStatus, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
  draft: 'default',
  issued: 'info',
  paid: 'success',
  overdue: 'error',
  cancelled: 'default',
}

function InvoiceLines({ invoiceId, format }: { invoiceId: string; format: CurrencyFormat }) {
  const { t, i18n } = useTranslation('billing')
  const query = useInvoiceDetailQuery(invoiceId)

  if (query.isPending) {
    return (
      <Typography variant="caption" color="text.secondary">
        {t('invoices.loadingLines')}
      </Typography>
    )
  }
  if (query.isError) {
    return <Alert severity="error">{t('invoices.linesError')}</Alert>
  }

  return (
    <Box sx={{ overflowX: 'auto', py: 1 }}>
      <Table size="small" aria-label={t('invoices.linesAriaLabel')}>
        <TableHead>
          <TableRow>
            <TableCell>{t('invoices.lineDescription')}</TableCell>
            <TableCell align="right">{t('usage.quantity')}</TableCell>
            <TableCell align="right">{t('usage.included')}</TableCell>
            <TableCell align="right">{t('usage.billable')}</TableCell>
            <TableCell align="right">{t('usage.unitPrice')}</TableCell>
            <TableCell align="right">{t('invoices.lineSubtotal')}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {query.data.lines.map((line, index) => (
            <TableRow key={`${line.metric_code}-${index}`}>
              <TableCell>{line.description}</TableCell>
              <TableCell align="right">{formatQuantity(line.quantity, i18n.language)}</TableCell>
              <TableCell align="right">
                {formatQuantity(line.included_quantity, i18n.language)}
              </TableCell>
              <TableCell align="right">
                {formatQuantity(line.billable_quantity, i18n.language)}
              </TableCell>
              <TableCell align="right">
                {formatUnitPrice(line.unit_amount, format, i18n.language)}
              </TableCell>
              <TableCell align="right">
                {formatMoney(line.subtotal, format, i18n.language)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )
}

/**
 * Issued invoices — the only documents that legally state what is owed.
 *
 * Kept visually distinct from everything above it for exactly that reason: the
 * cards and charts are estimates, and this is the bill. Lines load only when a
 * row is expanded, because a customer with two years of history does not need
 * twenty-four invoices' worth of lines to read the totals.
 */
export function InvoiceHistoryPanel({
  invoices,
  format,
}: {
  invoices: InvoiceSummary[]
  format: CurrencyFormat
}) {
  const { t, i18n } = useTranslation('billing')
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={0.5} sx={{ mb: 2 }}>
          <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
            {t('invoices.title')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('invoices.subtitle')}
          </Typography>
        </Stack>

        {invoices.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('invoices.empty')}
          </Typography>
        ) : (
          <Box sx={{ overflowX: 'auto' }}>
            <Table aria-label={t('invoices.tableAriaLabel')}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 48 }} />
                  <TableCell>{t('invoices.number')}</TableCell>
                  <TableCell>{t('invoices.period')}</TableCell>
                  <TableCell>{t('invoices.status')}</TableCell>
                  <TableCell>{t('invoices.due')}</TableCell>
                  <TableCell align="right">{t('invoices.total')}</TableCell>
                  <TableCell align="right">{t('invoices.outstanding')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {invoices.map((invoice) => {
                  const open = expanded === invoice.id
                  return (
                    // The fragment carries the key, not its children: a
                    // keyed child inside an unkeyed fragment is a React
                    // warning and defeats the reconciliation it exists for.
                    <Fragment key={invoice.id}>
                      <TableRow hover>
                        <TableCell>
                          <IconButton
                            size="small"
                            onClick={() => setExpanded(open ? null : invoice.id)}
                            aria-expanded={open}
                            aria-label={t('invoices.toggleLines', {
                              number: invoice.invoice_number ?? invoice.id,
                            })}
                          >
                            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
                          </IconButton>
                        </TableCell>
                        <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {invoice.invoice_number ?? '—'}
                        </TableCell>
                        <TableCell>
                          {formatDay(invoice.period_start.slice(0, 10), i18n.language)}
                        </TableCell>
                        <TableCell>
                          <Stack
                            direction="row"
                            spacing={0.5}
                            sx={{ alignItems: 'center', flexWrap: 'wrap' }}
                          >
                            <Chip
                              size="small"
                              color={STATUS_COLOUR[invoice.status]}
                              label={t(`invoices.statusLabel.${invoice.status}`)}
                            />
                            {invoice.days_overdue > 0 ? (
                              <Typography variant="caption" color="error.main">
                                {t('invoices.daysOverdue', { days: invoice.days_overdue })}
                              </Typography>
                            ) : null}
                          </Stack>
                        </TableCell>
                        <TableCell>
                          {invoice.due_date ? formatDay(invoice.due_date, i18n.language) : '—'}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatMoney(invoice.total_amount, format, i18n.language)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatMoney(invoice.amount_outstanding, format, i18n.language)}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={7} sx={{ py: 0, border: 0 }}>
                          <Collapse in={open} unmountOnExit>
                            {open ? <InvoiceLines invoiceId={invoice.id} format={format} /> : null}
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  )
                })}
              </TableBody>
            </Table>
          </Box>
        )}
      </CardContent>
    </Card>
  )
}
