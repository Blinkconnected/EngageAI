import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router-dom'
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
import FormControlLabel from '@mui/material/FormControlLabel'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import {
  useAgingQuery,
  useCollectionsStatusQuery,
  useExemptionMutation,
  useReinstateMutation,
  useRunCollectionsMutation,
} from './api'
import { formatDay, formatMoment } from './format'
import { Amount, Count, StandingChip } from './Money'
import type { CompanyStanding, CurrencyAging } from './types'

function errorText(error: unknown): string | null {
  if (!error) return null
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  if (typeof detail === 'string') return detail
  return (error as Error).message ?? null
}

/**
 * How overdue the money is, in the bands a debtors report uses.
 *
 * Every bucket is shown even when empty, so a column never silently vanishes
 * and a reader comparing this month to last is comparing the same shape.
 * An invoice lands in exactly one bucket, so the buckets sum to the total —
 * within a currency, which is the only place a sum exists here.
 */
function AgingTable({ books }: { books: CurrencyAging }) {
  const { t } = useTranslation('billingOps')

  return (
    <Card variant="outlined" sx={{ flex: '1 1 420px', minWidth: 360 }}>
      <CardContent>
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: 'baseline', justifyContent: 'space-between', mb: 1 }}
        >
          <Chip size="small" label={books.currency} />
          <Typography variant="body2">
            {t('collections.totalOutstanding')}{' '}
            <Amount value={books.total_outstanding} currency={books.currency} bold />
          </Typography>
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('collections.bucket')}</TableCell>
              <TableCell align="right">{t('collections.invoices')}</TableCell>
              <TableCell align="right">{t('collections.outstanding')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {books.buckets.map((bucket) => (
              <TableRow key={bucket.bucket}>
                <TableCell>
                  <Typography variant="body2">{t(`agingBucket.${bucket.bucket}`)}</Typography>
                </TableCell>
                <TableCell align="right">
                  <Count value={bucket.invoice_count} />
                </TableCell>
                <TableCell align="right">
                  <Amount
                    value={bucket.amount_outstanding}
                    currency={books.currency}
                    colour={
                      bucket.bucket === 'days_90_plus' && Number(bucket.amount_outstanding) > 0
                        ? 'error.main'
                        : undefined
                    }
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/** Marking a company the sweep must never suspend on its own. */
function ExemptionDialog({
  company,
  onClose,
}: {
  company: CompanyStanding | null
  onClose: () => void
}) {
  const { t } = useTranslation('billingOps')
  const exemption = useExemptionMutation()
  const [exempt, setExempt] = useState(false)
  const [reason, setReason] = useState('')

  const close = () => {
    exemption.reset()
    setReason('')
    onClose()
  }

  return (
    <Dialog
      open={Boolean(company)}
      onClose={close}
      fullWidth
      maxWidth="sm"
      // Seeded from the company each time it opens rather than held in
      // sync: a switch that shows the previous company's setting for a
      // frame is a switch somebody will act on. Keying on the company id
      // remounts the dialog — and its state — per company.
      key={company?.company_id}
      slotProps={{
        transition: { onEnter: () => setExempt(company?.never_auto_suspend ?? false) },
      }}
    >
      <DialogTitle>{t('collections.exemptionTitle')}</DialogTitle>
      {exemption.isPending && <LinearProgress />}
      <DialogContent dividers>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('collections.exemptionHelp')}
          </Typography>
          {exemption.error && <Alert severity="error">{errorText(exemption.error)}</Alert>}
          <FormControlLabel
            control={
              <Switch checked={exempt} onChange={(event) => setExempt(event.target.checked)} />
            }
            label={t('collections.neverAutoSuspend')}
          />
          <TextField
            label={t('collections.reason')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            size="small"
            multiline
            minRows={2}
            required
            helperText={t('collections.exemptionReasonHelp')}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{t('actions.cancel')}</Button>
        <Button
          variant="contained"
          disabled={!reason.trim() || exemption.isPending}
          onClick={() =>
            company &&
            exemption.mutate(
              {
                companyId: company.company_id,
                body: { never_auto_suspend: exempt, reason: reason.trim() },
              },
              { onSuccess: close },
            )
          }
        >
          {t('actions.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

/** Who is behind, how far, and what happens next. */
export function CollectionsPage() {
  const { t, i18n } = useTranslation('billingOps')
  const aging = useAgingQuery()
  const standings = useCollectionsStatusQuery()
  const run = useRunCollectionsMutation()
  const reinstate = useReinstateMutation()
  const [exempting, setExempting] = useState<CompanyStanding | null>(null)

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}
      >
        <Box>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
            {t('collections.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('collections.subtitle')}
          </Typography>
        </Box>
        <Tooltip title={t('collections.runHelp')}>
          <span>
            <Button
              variant="outlined"
              size="small"
              disabled={run.isPending}
              onClick={() => run.mutate()}
            >
              {t('collections.run')}
            </Button>
          </span>
        </Tooltip>
      </Stack>

      {run.isPending && <LinearProgress />}
      {run.error && <Alert severity="error">{errorText(run.error)}</Alert>}
      {run.data && (
        <Alert severity="success" onClose={() => run.reset()}>
          {t('collections.runResult', {
            overdue: run.data.marked_overdue,
            notices: run.data.notices_sent,
          })}
          {/* Names, not counts. An operator about to field a phone call
              needs to know which customer was cut off. */}
          {run.data.suspended.length > 0 && (
            <Box sx={{ mt: 0.5 }}>
              {t('collections.runSuspended', { names: run.data.suspended.join(', ') })}
            </Box>
          )}
          {run.data.reinstated.length > 0 && (
            <Box sx={{ mt: 0.5 }}>
              {t('collections.runReinstated', { names: run.data.reinstated.join(', ') })}
            </Box>
          )}
        </Alert>
      )}

      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
          {t('collections.aging')}
        </Typography>
        {aging.isFetching && <LinearProgress />}
        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
          {aging.data?.currencies.map((books) => (
            <AgingTable key={books.currency} books={books} />
          ))}
          {aging.data?.currencies.length === 0 && (
            <Alert severity="success" sx={{ flex: 1 }}>
              {t('collections.nothingOutstanding')}
            </Alert>
          )}
        </Stack>
        {aging.data && (
          <Typography variant="caption" color="text.secondary">
            {t('collections.agingAsOf', {
              moment: formatMoment(aging.data.as_of, i18n.language),
            })}
          </Typography>
        )}
      </Box>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {t('collections.whoIsBehind')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('collections.whoIsBehindHelp')}
          </Typography>
          {standings.isFetching && <LinearProgress />}
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('collections.company')}</TableCell>
                <TableCell>{t('collections.standing')}</TableCell>
                <TableCell align="right">{t('collections.openInvoices')}</TableCell>
                <TableCell align="right">{t('collections.overdueInvoices')}</TableCell>
                <TableCell align="right">{t('collections.outstanding')}</TableCell>
                <TableCell>{t('collections.nextAction')}</TableCell>
                <TableCell align="right">{t('payments.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {standings.data?.map((row) => (
                <TableRow key={row.company_id} hover>
                  <TableCell>
                    <Button
                      component={RouterLink}
                      to={`/platform/billing/companies/${row.company_id}`}
                      size="small"
                      sx={{ textTransform: 'none', p: 0, minWidth: 0 }}
                    >
                      {row.company_name}
                    </Button>
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                      <StandingChip status={row.billing_status} />
                      {row.never_auto_suspend && (
                        <Tooltip title={t('collections.exemptHelp')} disableInteractive>
                          <Chip size="small" variant="outlined" label={t('collections.exempt')} />
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    <Count value={row.open_invoices} />
                  </TableCell>
                  <TableCell align="right">
                    <Count value={row.overdue_invoices} />
                  </TableCell>
                  <TableCell align="right">
                    {/* No currency column and no total row, on purpose:
                        this list spans companies billing in different
                        currencies, and the amounts on it must never be
                        added together. Each one carries its own. */}
                    <Amount
                      value={row.amount_outstanding}
                      currency={row.currency}
                      colour={row.overdue_invoices > 0 ? 'warning.main' : undefined}
                    />
                  </TableCell>
                  <TableCell>{formatDay(row.next_action_on, i18n.language)}</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                      {row.billing_status === 'payment_suspended' && (
                        <Button
                          size="small"
                          disabled={reinstate.isPending}
                          onClick={() => reinstate.mutate(row.company_id)}
                        >
                          {t('collections.reinstate')}
                        </Button>
                      )}
                      <Button size="small" onClick={() => setExempting(row)}>
                        {t('collections.exemption')}
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
              {standings.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Typography variant="body2" color="text.secondary">
                      {t('collections.everybodyIsCurrent')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {reinstate.error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {errorText(reinstate.error)}
            </Alert>
          )}
        </CardContent>
      </Card>

      <ExemptionDialog company={exempting} onClose={() => setExempting(null)} />
    </Stack>
  )
}
