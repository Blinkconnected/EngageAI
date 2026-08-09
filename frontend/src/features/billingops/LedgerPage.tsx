import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
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

import { useLedgerStatementQuery, useTrialBalanceQuery } from './api'
import { CompanyPicker } from './CompanyPicker'
import { formatMoment } from './format'
import { Amount, Figure } from './Money'
import type { LedgerAccount } from './types'

const ACCOUNTS: LedgerAccount[] = [
  'accounts_receivable',
  'customer_credit',
  'cash',
  'revenue',
  'revenue_adjustments',
  'bad_debt',
]

const PAGE_SIZE = 100

/**
 * The books, and the proof they balance.
 *
 * One set per currency, never combined: adding dinars to dollars produces a
 * number that means nothing, and nothing here stores an exchange rate to make
 * it mean something. `in_balance` is answered by the server — comparing two
 * decimal strings in JavaScript is not proof of anything.
 */
function TrialBalance() {
  const { t } = useTranslation('billingOps')
  const query = useTrialBalanceQuery()

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {t('ledger.trialBalance')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t('ledger.trialBalanceHelp')}
        </Typography>
        {query.isFetching && <LinearProgress />}
        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
          {query.data?.map((books) => (
            <Box key={books.currency} sx={{ flex: '1 1 320px', minWidth: 300 }}>
              <Stack
                direction="row"
                spacing={1}
                sx={{ alignItems: 'center', mb: 1, flexWrap: 'wrap' }}
              >
                <Chip size="small" label={books.currency} />
                <Chip
                  size="small"
                  color={books.in_balance ? 'success' : 'error'}
                  variant={books.in_balance ? 'outlined' : 'filled'}
                  label={books.in_balance ? t('ledger.inBalance') : t('ledger.outOfBalance')}
                />
                <Typography variant="caption" color="text.secondary">
                  {t('ledger.entryCount', { count: books.entry_count })}
                </Typography>
              </Stack>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('ledger.account')}</TableCell>
                    <TableCell align="right">{t('ledger.debits')}</TableCell>
                    <TableCell align="right">{t('ledger.credits')}</TableCell>
                    <TableCell align="right">{t('ledger.balance')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {books.accounts.map((row) => (
                    <TableRow key={row.account}>
                      <TableCell>{t(`ledgerAccount.${row.account}`)}</TableCell>
                      <TableCell align="right">
                        <Amount value={row.debits} currency={books.currency} />
                      </TableCell>
                      <TableCell align="right">
                        <Amount value={row.credits} currency={books.currency} />
                      </TableCell>
                      <TableCell align="right">
                        <Amount value={row.balance} currency={books.currency} bold />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ))}
        </Stack>
      </CardContent>
    </Card>
  )
}

/**
 * One company's account, oldest first, with a balance carried down.
 *
 * Chronological — the opposite of the entry log — because a running balance
 * only reads as a balance if the rows arrive in the order they happened.
 *
 * Which account is being run down is a choice and is stated: receivable
 * answers "what do they owe us", customer credit answers "what do we hold for
 * them", and the two run in opposite directions. A balance with no account
 * beside it is not an answer to anything.
 */
export function LedgerPage() {
  const { t, i18n } = useTranslation('billingOps')
  const [company, setCompany] = useState<string | null>(null)
  const [account, setAccount] = useState<LedgerAccount>('accounts_receivable')
  const [currency, setCurrency] = useState('')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [page, setPage] = useState(0)

  const query = useLedgerStatementQuery(company, {
    account,
    currency: currency || undefined,
    since: since ? new Date(`${since}T00:00:00Z`).toISOString() : undefined,
    until: until ? new Date(`${until}T00:00:00Z`).toISOString() : undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })
  const statement = query.data

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
          {t('ledger.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('ledger.subtitle')}
        </Typography>
      </Box>

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
            <CompanyPicker
              value={company}
              onChange={(next) => {
                setCompany(next)
                setPage(0)
                // The currency belongs to the company that was chosen, not
                // to the next one. Carrying it over asks for a statement in
                // a currency this company may have no entries in.
                setCurrency('')
              }}
            />
            <TextField
              select
              size="small"
              label={t('ledger.account')}
              value={account}
              onChange={(event) => {
                setAccount(event.target.value as LedgerAccount)
                setPage(0)
              }}
              sx={{ minWidth: 200 }}
            >
              {ACCOUNTS.map((option) => (
                <MenuItem key={option} value={option}>
                  {t(`ledgerAccount.${option}`)}
                </MenuItem>
              ))}
            </TextField>
            {(statement?.available_currencies.length ?? 0) > 1 && (
              <TextField
                select
                size="small"
                label={t('filters.currency')}
                value={currency || statement?.currency || ''}
                onChange={(event) => {
                  setCurrency(event.target.value)
                  setPage(0)
                }}
                sx={{ minWidth: 120 }}
              >
                {statement?.available_currencies.map((code) => (
                  <MenuItem key={code} value={code}>
                    {code}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              type="date"
              size="small"
              label={t('filters.from')}
              value={since}
              onChange={(event) => {
                setSince(event.target.value)
                setPage(0)
              }}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              type="date"
              size="small"
              label={t('filters.until')}
              value={until}
              onChange={(event) => {
                setUntil(event.target.value)
                setPage(0)
              }}
              slotProps={{ inputLabel: { shrink: true } }}
              helperText={t('filters.untilExclusive')}
            />
          </Stack>
        </CardContent>
      </Card>

      {!company && <Alert severity="info">{t('ledger.pickACompany')}</Alert>}
      {query.isFetching && <LinearProgress />}
      {query.isError && <Alert severity="error">{t('ledger.loadFailed')}</Alert>}

      {statement && (
        <Card variant="outlined">
          <CardContent>
            <Stack
              direction="row"
              spacing={4}
              sx={{ flexWrap: 'wrap', rowGap: 2, mb: 2, alignItems: 'flex-start' }}
            >
              <Figure
                label={t('ledger.opening')}
                value={<Amount value={statement.opening_balance} currency={statement.currency} />}
                caption={t('ledger.openingCaption')}
              />
              <Figure
                label={t('ledger.closing')}
                value={
                  <Amount value={statement.closing_balance} currency={statement.currency} bold />
                }
                caption={t(`ledgerAccount.${statement.account}`)}
                emphasis
              />
              <Box sx={{ flexGrow: 1 }} />
              <Chip size="small" label={statement.currency} />
            </Stack>

            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('ledger.when')}</TableCell>
                  <TableCell>{t('ledger.entry')}</TableCell>
                  <TableCell>{t('ledger.reference')}</TableCell>
                  <TableCell align="right">{t('ledger.debit')}</TableCell>
                  <TableCell align="right">{t('ledger.credit')}</TableCell>
                  <TableCell align="right">{t('ledger.balance')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {page > 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography variant="body2" color="text.secondary">
                        {t('ledger.broughtForward')}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Amount
                        value={statement.page_opening_balance}
                        currency={statement.currency}
                      />
                    </TableCell>
                  </TableRow>
                )}
                {statement.rows.map((row) => (
                  <TableRow key={row.entry.id} hover>
                    <TableCell>{formatMoment(row.entry.occurred_at, i18n.language)}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                        <Typography variant="body2">
                          {t(`ledgerEntry.${row.entry.entry_type}`)}
                        </Typography>
                        {row.entry.reconstructed && (
                          <Tooltip title={t('ledger.reconstructedHelp')} disableInteractive>
                            <Chip
                              size="small"
                              variant="outlined"
                              label={t('ledger.reconstructed')}
                            />
                          </Tooltip>
                        )}
                      </Stack>
                      <Typography variant="caption" color="text.secondary">
                        {row.entry.description}
                      </Typography>
                    </TableCell>
                    <TableCell>{row.entry.reference_number ?? '—'}</TableCell>
                    <TableCell align="right">
                      {row.debit ? <Amount value={row.debit} currency={row.entry.currency} /> : '—'}
                    </TableCell>
                    <TableCell align="right">
                      {row.credit ? (
                        <Amount value={row.credit} currency={row.entry.currency} />
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Amount value={row.balance} currency={statement.currency} bold />
                    </TableCell>
                  </TableRow>
                ))}
                {statement.rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Typography variant="body2" color="text.secondary">
                        {t('ledger.noEntries')}
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>

            {statement.total > PAGE_SIZE && (
              <TablePagination
                component="div"
                count={statement.total}
                page={page}
                onPageChange={(_, next) => setPage(next)}
                rowsPerPage={PAGE_SIZE}
                rowsPerPageOptions={[PAGE_SIZE]}
                labelRowsPerPage={t('pagination.perPage')}
                labelDisplayedRows={({ from, to, count }) =>
                  t('pagination.showing', { from, to, count })
                }
              />
            )}
          </CardContent>
        </Card>
      )}

      <TrialBalance />
    </Stack>
  )
}
