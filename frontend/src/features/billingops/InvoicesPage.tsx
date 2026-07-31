import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import LinearProgress from '@mui/material/LinearProgress'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TablePagination from '@mui/material/TablePagination'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import { downloadInvoiceCsv, useInvoiceSearchQuery } from './api'
import { CompanyPicker } from './CompanyPicker'
import { formatCount, formatDay } from './format'
import { InvoiceDetailDialog } from './InvoiceDetailDialog'
import { Amount, InvoiceStatusChip } from './Money'
import type { InvoiceSearchGroup, InvoiceSearchParams, InvoiceStatus } from './types'

const STATUSES: InvoiceStatus[] = ['draft', 'issued', 'paid', 'overdue', 'cancelled']
const PAGE_SIZES = [25, 50, 100]

/**
 * One currency's slice of the result.
 *
 * A table per currency, with its own subtotals. Not a presentation
 * preference — this is the shape the API returns, because nothing converts
 * between dollars and dinars and a single table inviting the eye down a
 * mixed column of amounts is inviting a sum that means nothing.
 *
 * The subtotals describe the **whole filter**, not this page, so they do not
 * shift as somebody pages through. Said out loud in the caption, because a
 * total that silently meant something else on page two would be worse than
 * no total at all.
 */
function CurrencyTable({
  group,
  onOpen,
}: {
  group: InvoiceSearchGroup
  onOpen: (invoiceId: string) => void
}) {
  const { t, i18n } = useTranslation('billingOps')

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: 'baseline', flexWrap: 'wrap', rowGap: 1, mb: 1.5 }}
        >
          <Chip size="small" label={group.currency} />
          <Typography variant="body2" color="text.secondary">
            {t('invoices.matchedCount', { count: group.invoice_count })}
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2">
            {t('invoices.billed')}{' '}
            <Amount value={group.total_amount} currency={group.currency} bold />
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('invoices.paid')}{' '}
            <Amount value={group.amount_paid} currency={group.currency} />
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('invoices.credited')}{' '}
            <Amount value={group.amount_credited} currency={group.currency} />
          </Typography>
          <Tooltip title={t('invoices.outstandingMeaning')} disableInteractive>
            <Typography variant="body2">
              {t('invoices.outstanding')}{' '}
              <Amount
                value={group.amount_outstanding}
                currency={group.currency}
                bold
                colour={Number(group.amount_outstanding) > 0 ? 'warning.main' : undefined}
              />
            </Typography>
          </Tooltip>
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {t('invoices.totalsDescribeTheFilter')}
        </Typography>

        <Table size="small" sx={{ mt: 1 }}>
          <TableHead>
            <TableRow>
              <TableCell>{t('invoices.number')}</TableCell>
              <TableCell>{t('invoices.customer')}</TableCell>
              <TableCell>{t('invoices.status')}</TableCell>
              <TableCell>{t('invoices.issuedAt')}</TableCell>
              <TableCell>{t('invoices.dueDate')}</TableCell>
              <TableCell align="right">{t('invoices.total')}</TableCell>
              <TableCell align="right">{t('invoices.paid')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {group.items.map((invoice) => (
              <TableRow
                key={invoice.id}
                hover
                sx={{ cursor: 'pointer' }}
                onClick={() => onOpen(invoice.id)}
              >
                <TableCell>{invoice.invoice_number ?? t('invoices.draftInvoice')}</TableCell>
                <TableCell>{invoice.customer_name}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                    <InvoiceStatusChip status={invoice.status} />
                    {/* A written-off invoice is still overdue and still
                        unpaid — both true. What changed is that nobody is
                        chasing it, which is exactly what an operator
                        looking at an old overdue row needs to know. */}
                    {invoice.written_off_at && (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={t('invoices.writtenOff')}
                        color="default"
                      />
                    )}
                  </Stack>
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
            {group.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7}>
                  <Typography variant="body2" color="text.secondary">
                    {t('invoices.moreOnAnotherPage')}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/** Cross-company invoice management. */
export function InvoicesPage() {
  const { t, i18n } = useTranslation('billingOps')
  // Seeded from the URL so "Manage invoices" on a company's workspace lands
  // on *that* company's documents. Read once, as an initial value: after
  // that the filter is the control's, and rewriting the URL on every
  // keystroke would fill the reader's back button with search states.
  const [params] = useSearchParams()
  const [company, setCompany] = useState<string | null>(params.get('company'))
  const [status, setStatus] = useState<InvoiceStatus | ''>('')
  const [number, setNumber] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(50)
  const [open, setOpen] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportFailed, setExportFailed] = useState(false)

  const filters: InvoiceSearchParams = {
    company_id: company ?? undefined,
    status: status || undefined,
    q: number || undefined,
    issued_from: from || undefined,
    issued_to: to || undefined,
    limit: pageSize,
    offset: page * pageSize,
  }
  const query = useInvoiceSearchQuery(filters)

  // Every filter change returns to the first page. Staying on page four of
  // a result that now has two is how a screen shows nothing and looks broken.
  const change = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value)
    setPage(0)
  }

  const total = query.data?.total ?? 0
  const cap = query.data?.export_row_cap ?? 0
  const willTruncate = total > cap

  const exportCsv = async () => {
    setExporting(true)
    setExportFailed(false)
    try {
      // The export follows the *filter*, not the page. A download that
      // returned only the rows on screen is the subtlest way to hand
      // somebody an incomplete reconciliation.
      const { limit: _limit, offset: _offset, ...unpaged } = filters
      await downloadInvoiceCsv(unpaged)
    } catch {
      setExportFailed(true)
    } finally {
      setExporting(false)
    }
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
          {t('invoices.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('invoices.subtitle')}
        </Typography>
      </Box>

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
            <CompanyPicker value={company} onChange={change(setCompany)} />
            <TextField
              select
              size="small"
              label={t('filters.status')}
              value={status}
              onChange={(event) =>
                change(setStatus)(event.target.value as InvoiceStatus | '')
              }
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="">{t('filters.anyStatus')}</MenuItem>
              {STATUSES.map((option) => (
                <MenuItem key={option} value={option}>
                  {t(`invoiceStatus.${option}`)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label={t('filters.invoiceNumber')}
              value={number}
              onChange={(event) => change(setNumber)(event.target.value)}
              sx={{ minWidth: 180 }}
            />
            <TextField
              size="small"
              type="date"
              label={t('filters.issuedFrom')}
              value={from}
              onChange={(event) => change(setFrom)(event.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              size="small"
              type="date"
              label={t('filters.issuedTo')}
              value={to}
              onChange={(event) => change(setTo)(event.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <Box sx={{ flexGrow: 1 }} />
            <Button
              variant="outlined"
              size="small"
              disabled={exporting || total === 0}
              onClick={() => void exportCsv()}
            >
              {t('invoices.exportCsv')}
            </Button>
          </Stack>

          {/* Announced before the download, not after. A finance team
              reconciling against a short file has no way to know it is
              short once it is on a disk. */}
          {willTruncate && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              {t('invoices.exportTruncated', {
                cap: formatCount(cap, i18n.language),
                total: formatCount(total, i18n.language),
              })}
            </Alert>
          )}
          {exportFailed && (
            <Alert severity="error" sx={{ mt: 2 }} onClose={() => setExportFailed(false)}>
              {t('invoices.exportFailed')}
            </Alert>
          )}
        </CardContent>
      </Card>

      {query.isFetching && <LinearProgress />}
      {query.isError && <Alert severity="error">{t('invoices.searchFailed')}</Alert>}

      {query.data?.currencies.map((group) => (
        <CurrencyTable key={group.currency} group={group} onOpen={setOpen} />
      ))}

      {query.data && total === 0 && (
        <Alert severity="info">{t('invoices.noMatches')}</Alert>
      )}

      {total > 0 && (
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={(_, next) => setPage(next)}
          rowsPerPage={pageSize}
          rowsPerPageOptions={PAGE_SIZES}
          onRowsPerPageChange={(event) => {
            setPageSize(Number(event.target.value))
            setPage(0)
          }}
          labelRowsPerPage={t('pagination.perPage')}
          labelDisplayedRows={({ from, to, count }) =>
            t('pagination.showing', { from, to, count })
          }
        />
      )}

      <InvoiceDetailDialog invoiceId={open} onClose={() => setOpen(null)} />
    </Stack>
  )
}
