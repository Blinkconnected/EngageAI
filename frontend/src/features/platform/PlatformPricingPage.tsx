import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatUnitPrice } from '../../shared/money'
import { extractErrorMessage } from '../../shared/api/errors'
import {
  useEffectivePricingQuery,
  usePricingHealthQuery,
  usePricingHistoryQuery,
  usePricingProfilesQuery,
  useSetPriceMutation,
} from './api'
import type { EffectivePrice, PricingScope } from './types'

const SCOPE_COLOR: Record<PricingScope, 'primary' | 'info' | 'default'> = {
  company: 'primary',
  profile: 'info',
  global: 'default',
}

/**
 * The pricing console: what every company pays by default, per metric.
 *
 * Prices are shown with `formatUnitPrice`, not `formatMoney` — a rate of
 * $0.0005 and one of $0.05 are a hundredfold apart and both collapse to
 * "$0.00"/"$0.05" at two decimal places, which in a pricing table makes
 * one look free and the other look identical to it.
 */
export function PlatformPricingPage() {
  const { t } = useTranslation('platform')
  const [profileId, setProfileId] = useState<string>('')
  const pricing = useEffectivePricingQuery(profileId ? { profileId } : {})
  const profiles = usePricingProfilesQuery()
  const health = usePricingHealthQuery()
  const history = usePricingHistoryQuery()
  const setPrice = useSetPriceMutation()

  const [editing, setEditing] = useState<EffectivePrice | null>(null)
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const selectedProfile = profiles.data?.find((profile) => profile.id === profileId)

  function openEditor(item: EffectivePrice) {
    setEditing(item)
    setAmount(item.unit_amount ?? '')
    setReason('')
    setError(null)
  }

  function handleSave() {
    if (!editing) return
    setError(null)
    setPrice.mutate(
      {
        metricCode: editing.metric_code,
        unitAmount: amount,
        // Applied immediately. The server accepts a small grace window
        // around "now", so an operator clicking Save is never refused
        // for having built the request a second ago.
        effectiveFrom: new Date().toISOString(),
        reason: reason || undefined,
        profileId: profileId || undefined,
        // Optimistic concurrency: send whichever the current state is,
        // so a second operator's concurrent edit is refused rather than
        // silently overwritten.
        ...(editing.rate_id
          ? { expectedCurrentRateId: editing.rate_id }
          : { expectNoCurrentRate: true }),
      },
      {
        onSuccess: () => setEditing(null),
        onError: (mutationError) =>
          setError(extractErrorMessage(mutationError, t('PlatformPricingPage.saveError'))),
      },
    )
  }

  return (
    <>
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
        {t('PlatformPricingPage.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('PlatformPricingPage.description')}
      </Typography>

      {health.data && !health.data.ok && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t('PlatformPricingPage.uncoveredWarning', {
            metrics: health.data.metrics
              .filter((metric) => !metric.covered)
              .map((metric) => metric.display_name)
              .join(', '),
          })}
        </Alert>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <TextField
        select
        size="small"
        label={t('PlatformPricingPage.scopeLabel')}
        value={profileId}
        onChange={(event) => setProfileId(event.target.value)}
        sx={{ minWidth: 260, mb: 2 }}
      >
        <MenuItem value="">{t('PlatformPricingPage.globalDefault')}</MenuItem>
        {(profiles.data ?? [])
          .filter((profile) => !profile.is_system)
          .map((profile) => (
            <MenuItem key={profile.id} value={profile.id}>
              {profile.name}
            </MenuItem>
          ))}
      </TextField>

      {selectedProfile && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('PlatformPricingPage.profileHint', { name: selectedProfile.name })}
        </Typography>
      )}

      {pricing.isPending && <CircularProgress size={24} />}
      {pricing.isError && (
        <Alert
          severity="error"
          action={
            <Button size="small" onClick={() => void pricing.refetch()}>
              {t('PlatformPricingPage.retry')}
            </Button>
          }
        >
          {t('PlatformPricingPage.loadError')}
        </Alert>
      )}

      {pricing.data && (
        <TableContainer sx={{ overflowX: 'auto', mb: 4 }}>
          <Table size="small" aria-label={t('PlatformPricingPage.tableAriaLabel')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('PlatformPricingPage.columnMetric')}</TableCell>
                <TableCell>{t('PlatformPricingPage.columnPrice')}</TableCell>
                <TableCell>{t('PlatformPricingPage.columnSource')}</TableCell>
                <TableCell align="right">{t('PlatformPricingPage.columnActions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {pricing.data.items.map((item) => (
                <TableRow key={item.metric_code}>
                  <TableCell>
                    <Typography variant="body2">{item.display_name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t('PlatformPricingPage.perUnit', {
                        unit: t(`PlatformPricingPage.unit.${item.unit}`),
                      })}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {item.unit_amount === null ? (
                      // Never "$0.00" — an unset price and a free one must
                      // not look the same in a pricing table.
                      <Typography variant="body2" color="warning.main">
                        {t('PlatformPricingPage.notSet')}
                      </Typography>
                    ) : (
                      formatUnitPrice(item.unit_amount)
                    )}
                  </TableCell>
                  <TableCell>
                    {item.scope && (
                      <Tooltip
                        title={
                          item.shadowed.length
                            ? item.shadowed
                                .map(
                                  (shadow) =>
                                    `${t(`PlatformPricingPage.scope.${shadow.scope}`)}: ${formatUnitPrice(shadow.unit_amount)}`,
                                )
                                .join(' · ')
                            : ''
                        }
                      >
                        <Chip
                          size="small"
                          variant="outlined"
                          color={SCOPE_COLOR[item.scope]}
                          label={t(`PlatformPricingPage.scope.${item.scope}`)}
                        />
                      </Tooltip>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => openEditor(item)}>
                      {t('PlatformPricingPage.editButton')}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
        {t('PlatformPricingPage.historyTitle')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {t('PlatformPricingPage.historyDescription')}
      </Typography>
      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small" aria-label={t('PlatformPricingPage.historyAriaLabel')}>
          <TableHead>
            <TableRow>
              <TableCell>{t('PlatformPricingPage.columnWhen')}</TableCell>
              <TableCell>{t('PlatformPricingPage.columnMetric')}</TableCell>
              <TableCell>{t('PlatformPricingPage.columnChange')}</TableCell>
              <TableCell>{t('PlatformPricingPage.columnWho')}</TableCell>
              <TableCell>{t('PlatformPricingPage.columnReason')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(history.data ?? []).map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>{new Date(entry.occurred_at).toLocaleString()}</TableCell>
                <TableCell>{entry.metric_code ?? '—'}</TableCell>
                <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {entry.old_unit_amount ? formatUnitPrice(entry.old_unit_amount) : '—'}
                  {' → '}
                  {entry.new_unit_amount ? formatUnitPrice(entry.new_unit_amount) : '—'}
                </TableCell>
                <TableCell>{entry.changed_by_email ?? entry.changed_by_name ?? '—'}</TableCell>
                <TableCell>{entry.reason ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {history.data?.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {t('PlatformPricingPage.historyEmpty')}
        </Typography>
      )}

      <Dialog open={editing !== null} onClose={() => setEditing(null)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {t('PlatformPricingPage.editTitle', { metric: editing?.display_name ?? '' })}
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('PlatformPricingPage.amountLabel')}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              helperText={t('PlatformPricingPage.amountHelp')}
              required
              fullWidth
            />
            <TextField
              label={t('PlatformPricingPage.reasonLabel')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              helperText={t('PlatformPricingPage.reasonHelp')}
              fullWidth
            />
            <Alert severity="info">{t('PlatformPricingPage.historyNote')}</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>{t('PlatformPricingPage.cancel')}</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={setPrice.isPending || !amount}
          >
            {t('PlatformPricingPage.save')}
          </Button>
        </DialogActions>
      </Dialog>
      <Box sx={{ height: 24 }} />
    </>
  )
}
