import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TablePagination from '@mui/material/TablePagination'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import {
  useAllocationsQuery,
  useCompanyPaymentsQuery,
  useRecordPaymentMutation,
  useRefundMutation,
  useRefundableQuery,
  useRefundsQuery,
  useReverseAllocationMutation,
} from './api'
import { CompanyPicker } from './CompanyPicker'
import { formatMoment } from './format'
import { Amount } from './Money'

function errorText(error: unknown): string | null {
  if (!error) return null
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  if (typeof detail === 'string') return detail
  return (error as Error).message ?? null
}

/**
 * Recording money that arrived outside the payment providers.
 *
 * A bank transfer, a cheque, a CliQ transfer somebody photographed. The
 * currency is deliberately **not** a field: a company is billed in exactly
 * one currency and the server takes it from the company, so an operator
 * cannot record dollars against a dinar customer and produce a payment that
 * will never allocate to anything.
 *
 * Recording is not allocating. The money lands as customer credit and stays
 * there until somebody applies it to a document — which is a second,
 * deliberate decision, and the reason a mis-keyed payment is recoverable.
 */
function RecordPaymentDialog({
  open,
  companyId,
  onClose,
}: {
  open: boolean
  companyId: string | null
  onClose: () => void
}) {
  const { t } = useTranslation('billingOps')
  const record = useRecordPaymentMutation()
  const [amount, setAmount] = useState('')
  const [receivedAt, setReceivedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [reference, setReference] = useState('')
  const [note, setNote] = useState('')

  const close = () => {
    record.reset()
    setAmount('')
    setReference('')
    setNote('')
    onClose()
  }

  const submit = () => {
    if (!companyId) return
    record.mutate(
      {
        company_id: companyId,
        amount,
        // Midday UTC rather than midnight: an operator picks a calendar
        // day, and midnight on that day is the previous day in half the
        // world's timezones — which would age the payment wrongly.
        received_at: new Date(`${receivedAt}T12:00:00Z`).toISOString(),
        reference: reference || undefined,
        note: note || undefined,
      },
      { onSuccess: close },
    )
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('payments.recordTitle')}</DialogTitle>
      {record.isPending && <LinearProgress />}
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Alert severity="info">{t('payments.recordHelp')}</Alert>
          {record.error && <Alert severity="error">{errorText(record.error)}</Alert>}
          <TextField
            label={t('payments.amount')}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            size="small"
            required
            // Text, not number: a spinner on a money field invites a
            // scroll wheel to change an amount somebody already typed.
            inputMode="decimal"
            helperText={t('payments.amountHelp')}
          />
          <TextField
            type="date"
            label={t('payments.receivedAt')}
            value={receivedAt}
            onChange={(event) => setReceivedAt(event.target.value)}
            size="small"
            required
            slotProps={{ inputLabel: { shrink: true } }}
            helperText={t('payments.receivedAtHelp')}
          />
          <TextField
            label={t('payments.reference')}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            size="small"
            helperText={t('payments.referenceHelp')}
          />
          <TextField
            label={t('payments.note')}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            size="small"
            multiline
            minRows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('actions.cancel')}</Button>
        <Button
          variant="contained"
          disabled={!companyId || !amount.trim() || record.isPending}
          onClick={submit}
        >
          {t('payments.record')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

/** Returning money, and the history of what has already been returned. */
function RefundDialog({ paymentId, onClose }: { paymentId: string | null; onClose: () => void }) {
  const { t, i18n } = useTranslation('billingOps')
  const refundable = useRefundableQuery(paymentId)
  const refunds = useRefundsQuery(paymentId)
  const refund = useRefundMutation()
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')

  const close = () => {
    refund.reset()
    setAmount('')
    setReason('')
    onClose()
  }

  return (
    <Dialog open={Boolean(paymentId)} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('payments.refundTitle')}</DialogTitle>
      {(refund.isPending || refundable.isLoading) && <LinearProgress />}
      <DialogContent dividers>
        <Stack spacing={2}>
          {refundable.data && (
            <Typography variant="body2">
              {t('payments.refundable')}{' '}
              <Amount value={refundable.data.refundable} currency={refundable.data.currency} bold />
            </Typography>
          )}
          {/* The ceiling comes from the server, which knows what has
              already been returned. A console that worked it out itself
              would eventually let somebody refund more than was paid. */}
          <Typography variant="caption" color="text.secondary">
            {t('payments.refundableHelp')}
          </Typography>

          {refund.error && <Alert severity="error">{errorText(refund.error)}</Alert>}

          <TextField
            label={t('payments.amount')}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            size="small"
            inputMode="decimal"
            required
          />
          <TextField
            label={t('payments.reason')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            size="small"
            multiline
            minRows={2}
            required
          />

          {(refunds.data?.length ?? 0) > 0 && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                {t('payments.previousRefunds')}
              </Typography>
              <Table size="small">
                <TableBody>
                  {refunds.data?.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell>
                        <Amount value={row.amount} currency={row.currency} />
                      </TableCell>
                      <TableCell>
                        <Chip size="small" variant="outlined" label={row.status} />
                      </TableCell>
                      <TableCell>{row.reason}</TableCell>
                      <TableCell align="right">
                        {formatMoment(row.created_at, i18n.language)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('actions.cancel')}</Button>
        <Button
          variant="contained"
          color="error"
          disabled={!amount.trim() || !reason.trim() || refund.isPending}
          onClick={() =>
            paymentId &&
            refund.mutate({ paymentId, amount, reason: reason.trim() }, { onSuccess: close })
          }
        >
          {t('payments.refund')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

/** Undoing an application of money — with the reason it required. */
function ReverseDialog({
  allocationId,
  onClose,
}: {
  allocationId: string | null
  onClose: () => void
}) {
  const { t } = useTranslation('billingOps')
  const reverse = useReverseAllocationMutation()
  const [reason, setReason] = useState('')

  const close = () => {
    reverse.reset()
    setReason('')
    onClose()
  }

  return (
    <Dialog open={Boolean(allocationId)} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('payments.reverseTitle')}</DialogTitle>
      {reverse.isPending && <LinearProgress />}
      <DialogContent dividers>
        <Stack spacing={2}>
          <Alert severity="warning">{t('payments.reverseHelp')}</Alert>
          {reverse.error && <Alert severity="error">{errorText(reverse.error)}</Alert>}
          <TextField
            label={t('payments.reason')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            size="small"
            multiline
            minRows={2}
            autoFocus
            required
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('actions.cancel')}</Button>
        <Button
          variant="contained"
          color="error"
          disabled={!reason.trim() || reverse.isPending}
          onClick={() =>
            allocationId &&
            reverse.mutate({ allocationId, reason: reason.trim() }, { onSuccess: close })
          }
        >
          {t('payments.reverse')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

/** Payments, and where each one went. */
export function PaymentsPage() {
  const { t, i18n } = useTranslation('billingOps')
  const [company, setCompany] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [refunding, setRefunding] = useState<string | null>(null)
  const [reversing, setReversing] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 50

  const payments = useCompanyPaymentsQuery(company)
  const allocations = useAllocationsQuery({
    company_id: company ?? undefined,
    limit: pageSize,
    offset: page * pageSize,
  })

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}
      >
        <Box>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
            {t('payments.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('payments.subtitle')}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <CompanyPicker value={company} onChange={setCompany} />
          <Button
            variant="contained"
            size="small"
            disabled={!company}
            onClick={() => setRecording(true)}
          >
            {t('payments.record')}
          </Button>
        </Stack>
      </Stack>

      {!company && <Alert severity="info">{t('payments.pickACompany')}</Alert>}

      {company && (
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
              {t('payments.received')}
            </Typography>
            {payments.isFetching && <LinearProgress />}
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('payments.receivedAt')}</TableCell>
                  <TableCell>{t('payments.reference')}</TableCell>
                  <TableCell>{t('payments.provider')}</TableCell>
                  <TableCell align="right">{t('payments.amount')}</TableCell>
                  <TableCell align="right">{t('payments.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {payments.data?.map((payment) => (
                  <TableRow key={payment.id} hover>
                    <TableCell>{formatMoment(payment.received_at, i18n.language)}</TableCell>
                    <TableCell>{payment.reference ?? '—'}</TableCell>
                    <TableCell>
                      {payment.provider ? (
                        <Chip size="small" variant="outlined" label={payment.provider} />
                      ) : (
                        <Chip size="small" variant="outlined" label={t('payments.manual')} />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Amount value={payment.amount} currency={payment.currency} />
                    </TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => setRefunding(payment.id)}>
                        {t('payments.refund')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {payments.data?.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography variant="body2" color="text.secondary">
                        {t('payments.none')}
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {t('payments.allocations')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('payments.allocationsHelp')}
          </Typography>
          {allocations.isFetching && <LinearProgress />}

          {allocations.data?.currencies.map((group) => (
            <Box key={group.currency} sx={{ mt: 2 }}>
              <Stack
                direction="row"
                spacing={2}
                sx={{ alignItems: 'baseline', flexWrap: 'wrap', rowGap: 1 }}
              >
                <Chip size="small" label={group.currency} />
                <Typography variant="body2">
                  {t('payments.applied')}{' '}
                  <Amount value={group.allocated_total} currency={group.currency} bold />
                </Typography>
                {Number(group.reversed_total) > 0 && (
                  <Typography variant="body2" color="text.secondary">
                    {t('payments.reversed')}{' '}
                    <Amount value={group.reversed_total} currency={group.currency} />
                  </Typography>
                )}
              </Stack>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('payments.allocatedAt')}</TableCell>
                    <TableCell>{t('invoices.number')}</TableCell>
                    <TableCell>{t('payments.reference')}</TableCell>
                    <TableCell align="right">{t('payments.amount')}</TableCell>
                    <TableCell align="right">{t('payments.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {group.allocations.map((allocation) => (
                    <TableRow
                      key={allocation.id}
                      hover
                      sx={{ opacity: allocation.reversed ? 0.6 : 1 }}
                    >
                      <TableCell>{formatMoment(allocation.allocated_at, i18n.language)}</TableCell>
                      <TableCell>{allocation.invoice_number ?? '—'}</TableCell>
                      <TableCell>{allocation.payment_reference ?? '—'}</TableCell>
                      <TableCell align="right">
                        <Amount value={allocation.amount} currency={allocation.currency} />
                      </TableCell>
                      <TableCell align="right">
                        {allocation.reversed ? (
                          // The reversal is shown as history rather than
                          // the row disappearing: money was applied and
                          // then un-applied, and both happened.
                          <Chip
                            size="small"
                            variant="outlined"
                            label={t('payments.reversedOn', {
                              moment: formatMoment(allocation.reversed_at, i18n.language),
                            })}
                          />
                        ) : (
                          <Button size="small" onClick={() => setReversing(allocation.id)}>
                            {t('payments.reverse')}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ))}

          {allocations.data?.total === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              {t('payments.noAllocations')}
            </Typography>
          )}

          {(allocations.data?.total ?? 0) > pageSize && (
            <TablePagination
              component="div"
              count={allocations.data?.total ?? 0}
              page={page}
              onPageChange={(_, next) => setPage(next)}
              rowsPerPage={pageSize}
              rowsPerPageOptions={[pageSize]}
              labelRowsPerPage={t('pagination.perPage')}
              labelDisplayedRows={({ from, to, count }) =>
                t('pagination.showing', { from, to, count })
              }
            />
          )}
        </CardContent>
      </Card>

      <RecordPaymentDialog
        open={recording}
        companyId={company}
        onClose={() => setRecording(false)}
      />
      <RefundDialog paymentId={refunding} onClose={() => setRefunding(null)} />
      <ReverseDialog allocationId={reversing} onClose={() => setReversing(null)} />
    </Stack>
  )
}
