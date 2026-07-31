import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useParams } from 'react-router-dom'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../../shared/api/client'
import { useCompanyStandingQuery } from './api'
import { formatDay, formatMoment } from './format'
import { Amount, Figure, InvoiceStatusChip, StandingChip } from './Money'
import type { Invoice } from './types'

/**
 * The platform-side view of one company's billing.
 *
 * Reads the same endpoints the customer's own billing page reads, through the
 * `/platform/billing/companies/{id}/*` wrappers — deliberately, so an
 * operator on the phone is looking at the figures the customer is looking at.
 * A second, platform-shaped set of responses would be a second way of
 * rounding money, and the two would eventually disagree in front of a
 * customer.
 */

/** Only the parts of the tenant dashboard this workspace shows.
 *
 * A narrow structural type rather than the whole response: the customer's
 * own billing page owns that shape, and restating all of it here would be a
 * second definition to keep in step with the first. */
interface DashboardSnapshot {
  overview: {
    company_name: string
    currency: string
    billing_status: string
    estimated_month_to_date: string
    projected_total: string | null
    projection_method: string
    outstanding_balance: string
    credit_balance: string
    next_invoice_on: string
    next_payment_due_on: string
    days_elapsed: number
    days_remaining: number
    no_open_period: boolean
  }
  estimate: {
    projection: {
      method: string
      method_explanation: string
      projected_total: string | null
      days_measured: number
      currency: string
      unavailable_explanation: string | null
    }
  }
}

function useCompanyDashboard(companyId: string | undefined) {
  return useQuery({
    queryKey: ['billing-ops', 'company', companyId, 'dashboard'],
    enabled: Boolean(companyId),
    queryFn: async (): Promise<DashboardSnapshot> => {
      const { data } = await apiClient.get(
        `/platform/billing/companies/${companyId}/dashboard`,
      )
      return data as DashboardSnapshot
    },
  })
}

function useCompanyInvoices(companyId: string | undefined) {
  return useQuery({
    queryKey: ['billing-ops', 'company', companyId, 'invoices'],
    enabled: Boolean(companyId),
    queryFn: async (): Promise<Invoice[]> => {
      const { data } = await apiClient.get<Invoice[]>(
        `/platform/billing/companies/${companyId}/invoices`,
      )
      return data
    },
  })
}

export function CompanyBillingWorkspace() {
  const { t, i18n } = useTranslation('billingOps')
  const { companyId } = useParams<{ companyId: string }>()
  const standing = useCompanyStandingQuery(companyId ?? null)
  const dashboard = useCompanyDashboard(companyId)
  const invoices = useCompanyInvoices(companyId)

  const overview = dashboard.data?.overview
  const projection = dashboard.data?.estimate.projection
  // No fallback: a company whose currency has not loaded yet is not a
  // dollar company, and saying so while the request is in flight is the
  // kind of small lie a finance console cannot afford.
  const currency = standing.data?.currency ?? overview?.currency ?? null

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}
      >
        <Box>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
            {standing.data?.company_name ?? t('company.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('company.subtitle')}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          {/* Pricing for this company lives on its own screen — same
              company, different job. Deciding what somebody is charged and
              chasing what they owe are done by different people on
              different days. */}
          <Button
            component={RouterLink}
            to={`/platform/billing/pricing/companies/${companyId}`}
            size="small"
            variant="outlined"
          >
            {t('company.openPricing')}
          </Button>
          <Button
            component={RouterLink}
            to="/platform/billing/ledger"
            size="small"
            variant="outlined"
          >
            {t('company.openLedger')}
          </Button>
        </Stack>
      </Stack>

      {(standing.isFetching || dashboard.isFetching) && <LinearProgress />}

      {standing.isError && <Alert severity="error">{t('company.loadFailed')}</Alert>}

      {standing.data && (
        <Card variant="outlined">
          <CardContent>
            <Stack direction="row" spacing={4} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
              <Figure
                label={t('company.standing')}
                value={<StandingChip status={standing.data.billing_status} />}
                caption={
                  standing.data.billing_suspended_at
                    ? t('company.suspendedOn', {
                        moment: formatMoment(
                          standing.data.billing_suspended_at,
                          i18n.language,
                        ),
                      })
                    : undefined
                }
              />
              <Figure
                label={t('company.outstanding')}
                value={
                  <Amount
                    value={standing.data.amount_outstanding}
                    currency={standing.data.currency}
                    colour={
                      standing.data.overdue_invoices > 0 ? 'warning.main' : undefined
                    }
                  />
                }
                caption={t('company.openInvoices', {
                  open: standing.data.open_invoices,
                  overdue: standing.data.overdue_invoices,
                })}
                emphasis
              />
              {overview && (
                <Figure
                  label={t('company.monthToDate')}
                  value={
                    <Amount
                      value={overview.estimated_month_to_date}
                      currency={overview.currency}
                    />
                  }
                  caption={t('company.monthToDateCaption', {
                    elapsed: overview.days_elapsed,
                    remaining: overview.days_remaining,
                  })}
                />
              )}
              {projection && (
                <Figure
                  label={t('company.projected')}
                  value={
                    projection.projected_total ? (
                      <Amount
                        value={projection.projected_total}
                        currency={projection.currency}
                      />
                    ) : (
                      <Typography variant="h6" component="span" color="text.secondary">
                        {t('company.projectionUnavailable')}
                      </Typography>
                    )
                  }
                  // The projection explains itself, in the server's own
                  // words. An operator quoting this to a customer has to
                  // be able to say where it came from — and when it cannot
                  // be produced, why not.
                  caption={
                    projection.projected_total
                      ? projection.method_explanation
                      : (projection.unavailable_explanation ?? undefined)
                  }
                />
              )}
              {overview && Number(overview.credit_balance) > 0 && (
                <Figure
                  label={t('company.creditHeld')}
                  value={
                    <Amount value={overview.credit_balance} currency={overview.currency} />
                  }
                  caption={t('company.creditHeldCaption')}
                />
              )}
              <Figure
                label={t('company.nextAction')}
                value={
                  <Typography variant="h6" component="span">
                    {formatDay(standing.data.next_action_on, i18n.language)}
                  </Typography>
                }
                caption={t('company.nextActionCaption')}
              />
              {standing.data.never_auto_suspend && (
                <Chip size="small" variant="outlined" label={t('collections.exempt')} />
              )}
            </Stack>
          </CardContent>
        </Card>
      )}

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            {t('company.invoiceHistory')}
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('invoices.number')}</TableCell>
                <TableCell>{t('invoices.status')}</TableCell>
                <TableCell>{t('invoices.issuedAt')}</TableCell>
                <TableCell>{t('invoices.dueDate')}</TableCell>
                <TableCell align="right">{t('invoices.total')}</TableCell>
                <TableCell align="right">{t('invoices.paid')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {invoices.data?.map((invoice) => (
                <TableRow key={invoice.id} hover>
                  <TableCell>{invoice.invoice_number ?? '—'}</TableCell>
                  <TableCell>
                    <InvoiceStatusChip status={invoice.status} />
                  </TableCell>
                  <TableCell>{formatDay(invoice.issued_at, i18n.language)}</TableCell>
                  <TableCell>{formatDay(invoice.due_date, i18n.language)}</TableCell>
                  <TableCell align="right">
                    <Amount value={invoice.total_amount} currency={invoice.currency} />
                  </TableCell>
                  <TableCell align="right">
                    <Amount value={invoice.amount_paid} currency={invoice.currency} />
                  </TableCell>
                </TableRow>
              ))}
              {invoices.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography variant="body2" color="text.secondary">
                      {t('company.noInvoices')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {/* Drafts are absent here, matching what the customer sees. An
              operator who needs them is doing invoice management, which
              has its own screen and can actually issue or discard one. */}
          <Typography variant="caption" color="text.secondary">
            {t('company.issuedOnly')}{' '}
            <Button
              component={RouterLink}
              to={`/platform/billing/invoices?company=${companyId}`}
              size="small"
              sx={{ textTransform: 'none' }}
            >
              {t('company.openInvoiceManagement')}
            </Button>
          </Typography>
        </CardContent>
      </Card>

      {currency && (
        <Typography variant="caption" color="text.secondary">
          {t('company.currencyNote', { currency })}
        </Typography>
      )}
    </Stack>
  )
}
