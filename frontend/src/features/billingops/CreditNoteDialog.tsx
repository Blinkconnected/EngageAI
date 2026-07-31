import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
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
import Typography from '@mui/material/Typography'

import { useCreditNoteMutation, useCreditNotePreviewQuery, useCreditableLinesQuery } from './api'
import { formatAmount, formatQuantity } from './format'
import { Amount } from './Money'
import type { CreditNoteLineSelection } from './types'

function errorText(error: unknown): string | null {
  if (!error) return null
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data
    ?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string } | undefined
    if (first?.msg) return first.msg
  }
  return (error as Error).message ?? null
}

/** A quantity is only a number if it parses as one. */
function asQuantity(text: string): number | null {
  if (!text.trim()) return null
  const value = Number(text)
  return Number.isFinite(value) && value > 0 ? value : null
}

/**
 * Crediting an invoice, line by line.
 *
 * The whole design follows one rule the product owner set: **nothing here can
 * be credited that does not trace back to an invoice line.** There is no
 * amount box. An operator picks lines and quantities; the price comes from the
 * line that was billed, and the totals come from the server.
 *
 * The preview is a server round trip rather than local arithmetic, on purpose.
 * The console multiplying quantity by price would be a second implementation
 * of what the save does — and the two would agree right up until the day
 * rounding, a tier or a currency made them differ, in front of a customer. So
 * the figure an operator approves is produced by the same code that writes the
 * document.
 */
export function CreditNoteDialog({
  invoiceId,
  onClose,
}: {
  invoiceId: string | null
  onClose: () => void
}) {
  const { t, i18n } = useTranslation('billingOps')
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')

  const creditable = useCreditableLinesQuery(invoiceId)
  const issue = useCreditNoteMutation()

  // Only lines with a real, positive quantity typed against them. A ticked
  // row with an empty box is somebody mid-thought, not a selection.
  const selections: CreditNoteLineSelection[] = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, text]) => asQuantity(text) !== null)
        .map(([invoice_line_id, quantity]) => ({ invoice_line_id, quantity })),
    [quantities],
  )
  const preview = useCreditNotePreviewQuery(invoiceId, selections)

  const close = () => {
    setQuantities({})
    setReason('')
    issue.reset()
    onClose()
  }

  const lines = creditable.data?.lines ?? []
  const exhausted = lines.length > 0 && lines.every((line) => Number(line.quantity_creditable) <= 0)
  const previewFailure = errorText(preview.error)

  const setQuantity = (lineId: string, text: string) =>
    setQuantities((current) => {
      const next = { ...current }
      if (text.trim()) next[lineId] = text
      else delete next[lineId]
      return next
    })

  return (
    <Dialog open={Boolean(invoiceId)} onClose={close} fullWidth maxWidth="md">
      <DialogTitle>
        {t('credit.title')}
        {creditable.data?.invoice_number && (
          <Typography variant="body2" color="text.secondary">
            {creditable.data.invoice_number}
          </Typography>
        )}
      </DialogTitle>

      {(creditable.isLoading || issue.isPending) && <LinearProgress />}

      <DialogContent dividers>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('credit.help')}
          </Typography>

          {creditable.isError && (
            <Alert severity="error">{errorText(creditable.error) ?? t('credit.loadFailed')}</Alert>
          )}

          {/* Said out loud rather than left to be discovered. When an older
              whole-invoice credit note consumed credit without naming a
              line, the line remainders add up to more than the invoice
              allows — and an operator who fills the form to the line limits
              would be refused on submit with no way to know why. */}
          {creditable.data && Number(creditable.data.unattributed_credited_amount) > 0 && (
            <Alert severity="info">
              {t('credit.wholeInvoiceCredited', {
                amount: formatAmount(
                  creditable.data.amount_creditable,
                  creditable.data.currency,
                  i18n.language,
                ),
              })}
            </Alert>
          )}

          {exhausted && <Alert severity="info">{t('credit.nothingCreditable')}</Alert>}

          {lines.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox" />
                  <TableCell>{t('credit.line')}</TableCell>
                  <TableCell align="right">{t('credit.billed')}</TableCell>
                  <TableCell align="right">{t('credit.alreadyCredited')}</TableCell>
                  <TableCell align="right">{t('credit.creditable')}</TableCell>
                  <TableCell align="right">{t('credit.unitPrice')}</TableCell>
                  <TableCell align="right" sx={{ width: 140 }}>
                    {t('credit.creditQuantity')}
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {lines.map((line) => {
                  const remaining = Number(line.quantity_creditable)
                  const typed = quantities[line.invoice_line_id] ?? ''
                  const value = asQuantity(typed)
                  const tooMuch = value !== null && value > remaining
                  const spent = remaining <= 0
                  return (
                    <TableRow key={line.invoice_line_id} sx={{ opacity: spent ? 0.5 : 1 }}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          size="small"
                          disabled={spent}
                          checked={typed !== ''}
                          onChange={(event) =>
                            // Ticking fills the box with everything the line
                            // has left, which is what an operator crediting a
                            // whole line wants and a starting point for one
                            // crediting part of it.
                            setQuantity(
                              line.invoice_line_id,
                              event.target.checked ? line.quantity_creditable : '',
                            )
                          }
                          slotProps={{ input: { 'aria-label': line.description } }}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">{line.description}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {line.unit}
                        </Typography>
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {formatQuantity(line.billable_quantity, i18n.language)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {formatQuantity(line.quantity_credited, i18n.language)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {formatQuantity(line.quantity_creditable, i18n.language)}
                      </TableCell>
                      <TableCell align="right">
                        <Amount value={line.unit_amount} currency={line.currency} />
                      </TableCell>
                      <TableCell align="right">
                        <TextField
                          size="small"
                          value={typed}
                          disabled={spent}
                          onChange={(event) =>
                            setQuantity(line.invoice_line_id, event.target.value)
                          }
                          error={tooMuch}
                          helperText={tooMuch ? t('credit.overRemainder') : undefined}
                          inputMode="decimal"
                          slotProps={{ htmlInput: { 'aria-label': t('credit.creditQuantity') } }}
                          sx={{ width: 130 }}
                        />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}

          <Divider />

          {/* The totals, from the server. Absent rather than guessed while a
              selection is being typed — a figure that flickers between a
              local estimate and the real one teaches an operator to distrust
              both. */}
          {selections.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('credit.selectSomething')}
            </Typography>
          ) : previewFailure ? (
            <Alert severity="warning">{previewFailure}</Alert>
          ) : preview.data ? (
            <Stack spacing={0.5} sx={{ alignItems: 'flex-end' }}>
              <Typography variant="body2" color="text.secondary">
                {t('credit.subtotal')}{' '}
                <Amount value={preview.data.subtotal_amount} currency={preview.data.currency} />
              </Typography>
              <Typography variant="subtitle1">
                {t('credit.total')}{' '}
                <Amount
                  value={preview.data.total_amount}
                  currency={preview.data.currency}
                  bold
                />
              </Typography>
              {/* Formatted, not interpolated raw: the API sends amounts at
                  storage scale, and "412.500000" in a sentence is machine
                  output where a person expects money. */}
              <Typography variant="caption" color="text.secondary">
                {t('credit.ceiling', {
                  amount: formatAmount(
                    preview.data.amount_creditable_after,
                    preview.data.currency,
                    i18n.language,
                  ),
                })}
              </Typography>
            </Stack>
          ) : (
            <Box sx={{ height: 4 }}>{preview.isFetching && <LinearProgress />}</Box>
          )}

          <TextField
            label={t('credit.reason')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            helperText={t('credit.reasonHelp')}
            multiline
            minRows={2}
            size="small"
            required
            fullWidth
          />

          {issue.error && <Alert severity="error">{errorText(issue.error)}</Alert>}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('actions.cancel')}</Button>
        <Button
          variant="contained"
          disabled={
            !invoiceId ||
            !reason.trim() ||
            selections.length === 0 ||
            // Only what the server has already accepted. Submitting a
            // selection whose preview was refused would put the refusal a
            // click later for no reason.
            !preview.data ||
            preview.isFetching ||
            issue.isPending
          }
          onClick={() =>
            invoiceId &&
            issue.mutate(
              { invoiceId, body: { lines: selections, reason: reason.trim() } },
              { onSuccess: close },
            )
          }
        >
          {t('credit.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
