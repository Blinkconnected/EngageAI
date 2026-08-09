import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router-dom'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Divider from '@mui/material/Divider'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import {
  fetchInvoicePdf,
  useCancelInvoiceMutation,
  useEmailInvoiceMutation,
  useInvoiceQuery,
  useIssueInvoiceMutation,
  useNoticesQuery,
  useWriteOffMutation,
} from './api'
import { CreditNoteDialog } from './CreditNoteDialog'
import { formatDay, formatMoment, formatQuantity } from './format'
import { Amount, InvoiceStatusChip } from './Money'
import type { InvoiceDetail } from './types'

type Intent = 'none' | 'cancel' | 'write_off'

/**
 * A reason, required before anything irreversible happens.
 *
 * Not politeness. Every one of these actions writes an immutable financial
 * audit record and a ledger entry, and the reason is the only part a human
 * writes — six months later it is the difference between "we credited them"
 * and "we credited them because we double-billed the March period".
 */
function ReasonForm({
  label,
  helper,
  confirmLabel,
  danger,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  label: string
  helper: string
  confirmLabel: string
  danger?: boolean
  pending: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const { t } = useTranslation('billingOps')
  const [reason, setReason] = useState('')

  return (
    <Stack spacing={1.5} sx={{ mt: 2 }}>
      <Divider />
      <Typography variant="subtitle2">{label}</Typography>
      <Typography variant="body2" color="text.secondary">
        {helper}
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField
        label={t('invoices.reason')}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        multiline
        minRows={2}
        size="small"
        autoFocus
        fullWidth
      />
      <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onCancel} disabled={pending}>
          {t('actions.back')}
        </Button>
        <Button
          size="small"
          variant="contained"
          color={danger ? 'error' : 'primary'}
          disabled={reason.trim().length === 0 || pending}
          onClick={() => onConfirm(reason.trim())}
        >
          {confirmLabel}
        </Button>
      </Stack>
    </Stack>
  )
}

function errorText(error: unknown): string | null {
  if (!error) return null
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  if (typeof detail === 'string') return detail
  return (error as Error).message ?? null
}

/** What was billed, line by line, with the allowance shown rather than
 * netted away — a customer asking "why 50 and not 150" is answered by the
 * three columns, not by a support conversation. */
function Lines({ detail }: { detail: InvoiceDetail }) {
  const { t, i18n } = useTranslation('billingOps')
  const currency = detail.invoice.currency

  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('invoices.line')}</TableCell>
          <TableCell align="right">{t('invoices.quantity')}</TableCell>
          <TableCell align="right">{t('invoices.included')}</TableCell>
          <TableCell align="right">{t('invoices.billable')}</TableCell>
          <TableCell align="right">{t('invoices.unitAmount')}</TableCell>
          <TableCell align="right">{t('invoices.subtotal')}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {detail.lines.map((line) => (
          <TableRow key={line.id}>
            <TableCell>
              <Typography variant="body2">{line.description}</Typography>
              <Typography variant="caption" color="text.secondary">
                {line.metric_code} · {line.unit}
              </Typography>
            </TableCell>
            <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatQuantity(line.quantity, i18n.language)}
            </TableCell>
            <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatQuantity(line.included_quantity, i18n.language)}
            </TableCell>
            <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatQuantity(line.billable_quantity, i18n.language)}
            </TableCell>
            <TableCell align="right">
              <Amount value={line.unit_amount} currency={currency} />
            </TableCell>
            <TableCell align="right">
              <Amount value={line.subtotal} currency={currency} />
            </TableCell>
          </TableRow>
        ))}
        {detail.lines.length === 0 && (
          <TableRow>
            <TableCell colSpan={6}>
              <Typography variant="body2" color="text.secondary">
                {t('invoices.noLines')}
              </Typography>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}

/**
 * One invoice, and everything that can be done to it.
 *
 * The action set is derived from the invoice's own status rather than from a
 * list of buttons that are always present and sometimes fail. A draft can be
 * issued; an issued invoice can be credited or written off; a cancelled one
 * can only be read. Offering an action that the API will refuse is how an
 * operator learns to ignore error messages.
 *
 * There is no "edit" and no "delete". An issued invoice is a financial
 * record — the corrections are a credit note (we billed too much) and a
 * write-off (we billed correctly and will not be paid), and both leave the
 * original standing.
 */
export function InvoiceDetailDialog({
  invoiceId,
  onClose,
}: {
  invoiceId: string | null
  onClose: () => void
}) {
  const { t, i18n } = useTranslation('billingOps')
  const [intent, setIntent] = useState<Intent>('none')
  const [crediting, setCrediting] = useState(false)
  const [pdfFailed, setPdfFailed] = useState(false)
  const [busy, setBusy] = useState<'download' | 'print' | null>(null)
  const query = useInvoiceQuery(invoiceId)
  const notices = useNoticesQuery(invoiceId)
  const issue = useIssueInvoiceMutation()
  const cancel = useCancelInvoiceMutation()
  const writeOff = useWriteOffMutation()
  const email = useEmailInvoiceMutation()

  const detail = query.data
  const invoice = detail?.invoice
  const pending = issue.isPending || cancel.isPending || writeOff.isPending
  const failure = errorText(issue.error ?? cancel.error ?? writeOff.error)

  // What this document actually permits, mirroring the engine's own rules
  // (``domain/invoicing.py``: the transition table, ``is_frozen``, and the
  // write-off's requirement that something be outstanding). Offering an
  // action the API will refuse is how an operator learns to ignore error
  // messages — and hiding one it would allow is how they learn the console
  // is not to be trusted.
  const owed = detail ? Number(detail.amount_outstanding) : 0
  const allowed = {
    issue: invoice?.status === 'draft',
    // A credit note corrects a document that has left the building. A
    // draft is changed by regenerating it.
    credit: Boolean(invoice && ['issued', 'overdue', 'paid'].includes(invoice.status)),
    // Only a live debt can be abandoned, and only once.
    writeOff: Boolean(
      invoice &&
      ['issued', 'overdue'].includes(invoice.status) &&
      !invoice.written_off_at &&
      owed > 0,
    ),
    cancelVisible: Boolean(invoice && ['draft', 'issued', 'overdue'].includes(invoice.status)),
    // Withdrawing a document somebody has paid against would leave their
    // money attached to nothing.
    cancel: Boolean(invoice && Number(invoice.amount_paid) === 0),
  }

  const openPdf = async (mode: 'download' | 'print') => {
    if (!invoice) return
    setBusy(mode)
    setPdfFailed(false)
    try {
      await fetchInvoicePdf(invoice.id, { open: mode === 'print' })
    } catch {
      setPdfFailed(true)
    } finally {
      setBusy(null)
    }
  }

  const close = () => {
    setIntent('none')
    setCrediting(false)
    setPdfFailed(false)
    email.reset()
    issue.reset()
    cancel.reset()
    writeOff.reset()
    onClose()
  }

  return (
    <Dialog open={Boolean(invoiceId)} onClose={close} fullWidth maxWidth="md">
      <DialogTitle>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{invoice?.invoice_number ?? t('invoices.draftInvoice')}</span>
          {invoice && <InvoiceStatusChip status={invoice.status} />}
        </Stack>
        {invoice && (
          <Typography variant="body2" color="text.secondary">
            {invoice.customer_name}
          </Typography>
        )}
      </DialogTitle>

      {(query.isLoading || pending) && <LinearProgress />}

      <DialogContent dividers>
        {query.isError && <Alert severity="error">{t('invoices.loadFailed')}</Alert>}

        {detail && invoice && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={4} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('invoices.period')}
                </Typography>
                <Typography variant="body2">
                  {formatDay(invoice.period_start, i18n.language)} —{' '}
                  {formatDay(invoice.period_end, i18n.language)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('invoices.issuedAt')}
                </Typography>
                <Typography variant="body2">
                  {formatMoment(invoice.issued_at, i18n.language)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('invoices.dueDate')}
                </Typography>
                <Typography variant="body2">
                  {formatDay(invoice.due_date, i18n.language)}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('invoices.paidAt')}
                </Typography>
                <Typography variant="body2">
                  {formatMoment(invoice.paid_at, i18n.language)}
                </Typography>
              </Box>
            </Stack>

            <Lines detail={detail} />

            <Stack spacing={0.5} sx={{ alignItems: 'flex-end' }}>
              <Typography variant="body2">
                {t('invoices.total')}{' '}
                <Amount value={invoice.total_amount} currency={invoice.currency} bold />
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('invoices.paid')}{' '}
                <Amount value={invoice.amount_paid} currency={invoice.currency} />
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('invoices.credited')}{' '}
                <Amount value={invoice.amount_credited} currency={invoice.currency} />
              </Typography>
            </Stack>

            {detail.credit_notes.length > 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  {t('invoices.creditNotes')}
                </Typography>
                <Table size="small">
                  <TableBody>
                    {detail.credit_notes.map((note) => (
                      <TableRow key={note.id}>
                        <TableCell>{note.credit_note_number}</TableCell>
                        <TableCell>{note.reason}</TableCell>
                        <TableCell>{formatMoment(note.issued_at, i18n.language)}</TableCell>
                        <TableCell align="right">
                          <Amount value={note.total_amount} currency={note.currency} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}

            {invoice.cancelled_at && (
              <Alert severity="warning">
                {t('invoices.cancelledOn', {
                  moment: formatMoment(invoice.cancelled_at, i18n.language),
                  reason: invoice.cancellation_reason ?? '',
                })}
              </Alert>
            )}

            {/* Every notice this invoice has generated. An operator on the
                phone with a customer who says they were never told needs to
                see what was sent and when. */}
            {(notices.data?.length ?? 0) > 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  {t('invoices.notices')}
                </Typography>
                <Table size="small">
                  <TableBody>
                    {notices.data?.map((notice) => (
                      <TableRow key={notice.id}>
                        <TableCell>{t(`dunningStage.${notice.stage}`)}</TableCell>
                        <TableCell>{notice.channels ?? '—'}</TableCell>
                        <TableCell align="right">
                          {formatMoment(notice.sent_at, i18n.language)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}

            {failure && intent === 'none' && <Alert severity="error">{failure}</Alert>}
            {pdfFailed && (
              <Alert severity="error" onClose={() => setPdfFailed(false)}>
                {t('invoices.pdfFailed')}
              </Alert>
            )}
            {email.data && (
              <Alert severity="success" onClose={() => email.reset()}>
                {t('invoices.emailSent', { recipients: email.data.sent_to.join(', ') })}
              </Alert>
            )}
            {email.error && (
              <Alert severity="error" onClose={() => email.reset()}>
                {errorText(email.error) ?? t('invoices.emailFailed')}
              </Alert>
            )}

            {intent === 'cancel' && (
              <ReasonForm
                label={t('invoices.cancelTitle')}
                helper={t('invoices.cancelHelp')}
                confirmLabel={t('invoices.cancelConfirm')}
                danger
                pending={pending}
                error={errorText(cancel.error)}
                onCancel={() => setIntent('none')}
                onConfirm={(reason) =>
                  cancel.mutate(
                    { invoiceId: invoice.id, reason },
                    { onSuccess: () => setIntent('none') },
                  )
                }
              />
            )}

            {intent === 'write_off' && (
              <ReasonForm
                label={t('invoices.writeOffTitle')}
                helper={t('invoices.writeOffHelp')}
                confirmLabel={t('invoices.writeOffConfirm')}
                danger
                pending={pending}
                error={errorText(writeOff.error)}
                onCancel={() => setIntent('none')}
                onConfirm={(reason) =>
                  writeOff.mutate(
                    { invoiceId: invoice.id, reason },
                    { onSuccess: () => setIntent('none') },
                  )
                }
              />
            )}
          </Stack>
        )}
      </DialogContent>

      <DialogActions sx={{ flexWrap: 'wrap', rowGap: 1 }}>
        {invoice && (
          <Button
            component={RouterLink}
            to={`/platform/billing/companies/${invoice.company_id}`}
            size="small"
            onClick={close}
          >
            {t('invoices.openCompany')}
          </Button>
        )}
        {/* Only an issued document has a PDF: a draft carries no number,
            nothing has been sent to anybody, and a file that looks like an
            invoice but is not one is the most confusing thing this dialog
            could hand somebody. */}
        {invoice && invoice.status !== 'draft' && (
          <>
            <Button size="small" disabled={busy !== null} onClick={() => void openPdf('print')}>
              {t('invoices.printPdf')}
            </Button>
            <Button size="small" disabled={busy !== null} onClick={() => void openPdf('download')}>
              {t('invoices.downloadPdf')}
            </Button>
            <Button
              size="small"
              disabled={email.isPending}
              onClick={() => email.mutate(invoice.id)}
            >
              {t('invoices.emailInvoice')}
            </Button>
          </>
        )}
        <Box sx={{ flexGrow: 1 }} />
        {invoice && intent === 'none' && (
          <>
            {allowed.issue && (
              <Button
                variant="contained"
                size="small"
                disabled={pending}
                onClick={() => issue.mutate(invoice.id)}
              >
                {t('invoices.issue')}
              </Button>
            )}
            {allowed.credit && (
              <Button size="small" onClick={() => setCrediting(true)} disabled={pending}>
                {t('invoices.creditNote')}
              </Button>
            )}
            {allowed.writeOff && (
              <Button
                size="small"
                color="error"
                onClick={() => setIntent('write_off')}
                disabled={pending}
              >
                {t('invoices.writeOff')}
              </Button>
            )}
            {allowed.cancelVisible && (
              <Tooltip title={allowed.cancel ? '' : t('invoices.cancelBlockedPaid')}>
                {/* A span, because a disabled button emits no hover events
                    and the tooltip explaining *why* would never appear. */}
                <span>
                  <Button
                    size="small"
                    color="error"
                    disabled={!allowed.cancel || pending}
                    onClick={() => setIntent('cancel')}
                  >
                    {t('invoices.cancel')}
                  </Button>
                </span>
              </Tooltip>
            )}
          </>
        )}
        <Button size="small" onClick={close}>
          {t('actions.close')}
        </Button>
      </DialogActions>

      <CreditNoteDialog
        invoiceId={crediting ? (invoice?.id ?? null) : null}
        onClose={() => setCrediting(false)}
      />
    </Dialog>
  )
}
