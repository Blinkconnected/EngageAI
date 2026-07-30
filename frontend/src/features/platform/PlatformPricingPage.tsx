import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
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
import {
  useBillableMetricsQuery,
  useEffectivePricingQuery,
  usePricingHealthQuery,
  usePricingHistoryQuery,
  usePricingModelsQuery,
  usePricingProfilesQuery,
} from './api'
import { UsageMetricPricingEditor } from './UsageMetricPricingEditor'
import type { EffectivePrice, PricingScope } from './types'
import { metricName } from './metricName'

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
  // Which price list is being read. Nothing converts, so a metric has one rate
  // per currency and every one of them is in force at once — "the global
  // price" is not a question that has an answer until a currency is named.
  const [currency, setCurrency] = useState<string>('')
  const pricing = useEffectivePricingQuery({
    ...(profileId ? { profileId } : {}),
    ...(currency ? { currency } : {}),
  })
  const profiles = usePricingProfilesQuery()
  const health = usePricingHealthQuery()
  const history = usePricingHistoryQuery()
  const models = usePricingModelsQuery()
  const metrics = useBillableMetricsQuery()

  const [editing, setEditing] = useState<EffectivePrice | null>(null)
  const [error, setError] = useState<string | null>(null)

  const selectedProfile = profiles.data?.find((profile) => profile.id === profileId)
  const metricsByCode = new Map((metrics.data ?? []).map((metric) => [metric.code, metric]))
  //: Declared but unmetered dimensions. Shown, because an operator asking
  //: "can I charge for tokens yet?" deserves the answer on the screen rather
  //: than by trying and being refused.
  const declared = (metrics.data ?? []).filter((metric) => metric.availability === 'planned')

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
              .map((metric) => metricName(t, metric))
              .join(', '),
          })}
        </Alert>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          select
          size="small"
          label={t('PlatformPricingPage.scopeLabel')}
          value={profileId}
          onChange={(event) => setProfileId(event.target.value)}
          sx={{ minWidth: 260 }}
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

        {/* The currency options come from the server, so the console never
            keeps its own copy of the currency table. Rendered only once
            there is a choice to make. */}
        {(pricing.data?.available_currencies?.length ?? 0) > 1 && (
          <TextField
            select
            size="small"
            label={t('PlatformPricingPage.currencyLabel')}
            value={currency || (pricing.data?.currency ?? '')}
            onChange={(event) => setCurrency(event.target.value)}
            sx={{ minWidth: 140 }}
            helperText={t('PlatformPricingPage.currencyHint')}
          >
            {(pricing.data?.available_currencies ?? []).map((code) => (
              <MenuItem key={code} value={code}>
                {code}
              </MenuItem>
            ))}
          </TextField>
        )}
      </Stack>

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
                    <Typography variant="body2">{metricName(t, item)}</Typography>
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
                    <Button size="small" onClick={() => setEditing(item)}>
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

      {/* Declared dimensions with no meter. Listed rather than hidden: an
          operator asking "can I charge for tokens yet?" gets the answer here
          instead of by trying and being refused. */}
      {declared.length > 0 && (
        <>
          <Typography variant="h6" component="h2" sx={{ mt: 4, mb: 1 }}>
            {t('PlatformPricingPage.declaredTitle')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {t('PlatformPricingPage.declaredDescription')}
          </Typography>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
            {declared.map((metric) => (
              <Tooltip key={metric.code} title={metric.description}>
                <Chip
                  size="small"
                  variant="outlined"
                  label={t('PlatformPricingPage.declaredChip', {
                    name: metricName(t, metric),
                    unit: t(`PlatformPricingPage.unit.${metric.unit}`, metric.unit),
                  })}
                />
              </Tooltip>
            ))}
          </Stack>
        </>
      )}

      {editing !== null && (
        <UsageMetricPricingEditor
          price={editing}
          metric={metricsByCode.get(editing.metric_code)}
          models={models.data ?? []}
          currency={pricing.data?.currency ?? ''}
          profileId={profileId || undefined}
          onClose={() => setEditing(null)}
        />
      )}
      <Box sx={{ height: 24 }} />
    </>
  )
}
