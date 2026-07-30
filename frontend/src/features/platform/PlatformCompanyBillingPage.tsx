import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useParams } from 'react-router-dom'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Collapse from '@mui/material/Collapse'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import {
  useAssignProfileMutation,
  useCompanyEffectivePricingQuery,
  useCompanyPricingHistoryQuery,
  usePlatformMeQuery,
  usePricingProfilesQuery,
  useResolvePriceMutation,
  useSetCompanyRateMutation,
} from './api'
import type { EffectivePrice, PricingScope, ResolveUsagePriceResponse } from './types'
import { metricName } from './metricName'

/** Where a price came from. Rendered from the resolver's own `scope`
 * field — the console never works out precedence for itself, because a
 * second implementation of the hierarchy would drift from the one that
 * actually bills. */
function SourceChip({ scope }: { scope: PricingScope | null }) {
  const { t } = useTranslation('platform')
  if (!scope) {
    return (
      <Chip
        size="small"
        color="error"
        variant="outlined"
        label={t('PlatformCompanyBillingPage.sourceNone')}
      />
    )
  }
  const colour = scope === 'company' ? 'primary' : scope === 'profile' ? 'info' : 'default'
  return (
    <Chip
      size="small"
      color={colour}
      variant={scope === 'global' ? 'outlined' : 'filled'}
      label={t(`PlatformCompanyBillingPage.source.${scope}`)}
    />
  )
}

/** The unit for a metric, from the effective-pricing table the server
 * already sent. The resolver's reply is about money and does not repeat
 * the metric's unit, and looking it up here beats a second request. */
function unitFor(items: EffectivePrice[], metricCode: string): string {
  return items.find((item) => item.metric_code === metricCode)?.unit ?? ''
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** An amount exactly as the server sent it, with the currency the server
 * said. Deliberately not `Intl.NumberFormat` on a parsed float: JOD has
 * three decimal places and USD two, the API already returns the value at
 * the right scale, and re-formatting a parsed number is how a displayed
 * price stops matching the billed one. */
function Amount({ value, currency }: { value: string | null; currency: string | null }) {
  if (value == null) return <>—</>
  return (
    <Box component="span" sx={{ fontVariantNumeric: 'tabular-nums' }}>
      {value} {currency ?? ''}
    </Box>
  )
}

export function PlatformCompanyBillingPage() {
  const { t } = useTranslation('platform')
  const { companyId = '' } = useParams()
  const me = usePlatformMeQuery()
  const readOnly = me.data?.read_only ?? false

  const pricing = useCompanyEffectivePricingQuery(companyId)
  const profiles = usePricingProfilesQuery()
  const history = useCompanyPricingHistoryQuery(companyId)
  const assignProfile = useAssignProfileMutation()

  const [editing, setEditing] = useState<EffectivePrice | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [preview, setPreview] = useState<ResolveUsagePriceResponse | null>(null)
  const [previewAt, setPreviewAt] = useState(new Date().toISOString().slice(0, 16))
  const [previewMetric, setPreviewMetric] = useState('')
  const resolve = useResolvePriceMutation()

  if (pricing.isPending) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }
  if (pricing.isError || !pricing.data) {
    return <Alert severity="error">{t('PlatformCompanyBillingPage.loadFailed')}</Alert>
  }

  const data = pricing.data

  const runPreview = () => {
    if (!previewMetric) return
    resolve.mutate(
      {
        companyId,
        metricCode: previewMetric,
        // Sent as an instant, because effective dating is to the second
        // and "which price applies today" is a different question from
        // "which applies right now".
        at: new Date(previewAt).toISOString(),
      },
      { onSuccess: setPreview },
    )
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Button component={RouterLink} to="/platform" size="small" sx={{ mb: 1 }}>
          {t('PlatformCompanyBillingPage.backToCompanies')}
        </Button>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          {t('PlatformCompanyBillingPage.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('PlatformCompanyBillingPage.subtitle', { currency: data.currency })}
        </Typography>
      </Box>

      {readOnly && <Alert severity="info">{t('PlatformCompanyBillingPage.readOnlyNotice')}</Alert>}

      {/* --- Pricing profile ------------------------------------------ */}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('PlatformCompanyBillingPage.profileTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('PlatformCompanyBillingPage.profileSubtitle')}
              </Typography>
            </Box>
            <ProfileAssignment
              companyId={companyId}
              currentProfileId={data.profile_id}
              currentProfileName={data.profile_name}
              profiles={profiles.data ?? []}
              readOnly={readOnly}
              onAssign={(input) => assignProfile.mutate(input)}
              pending={assignProfile.isPending}
              failed={assignProfile.isError}
            />
          </Stack>
        </CardContent>
      </Card>

      {/* --- Effective pricing --------------------------------------- */}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={1.5}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('PlatformCompanyBillingPage.effectiveTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('PlatformCompanyBillingPage.effectiveSubtitle', {
                  when: new Date(data.resolved_at).toLocaleString(),
                })}
              </Typography>
            </Box>
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('PlatformCompanyBillingPage.colMetric')}</TableCell>
                    <TableCell align="right">{t('PlatformCompanyBillingPage.colPrice')}</TableCell>
                    <TableCell>{t('PlatformCompanyBillingPage.colSource')}</TableCell>
                    <TableCell>{t('PlatformCompanyBillingPage.colFrom')}</TableCell>
                    <TableCell>{t('PlatformCompanyBillingPage.colUntil')}</TableCell>
                    <TableCell align="right" />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.items.map((item) => (
                    <TableRow key={item.metric_code} hover>
                      <TableCell>
                        <Typography variant="body2">{metricName(t, item)}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {t('PlatformCompanyBillingPage.perUnit', { unit: item.unit })}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Amount value={item.unit_amount} currency={item.currency} />
                      </TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                          <SourceChip scope={item.scope} />
                          {/* What *lost*. An override that is itself
                              overridden looks applied unless the
                              hierarchy is visible. */}
                          {item.shadowed.length > 0 && (
                            <Button
                              size="small"
                              onClick={() =>
                                setExpanded(expanded === item.metric_code ? null : item.metric_code)
                              }
                            >
                              {t('PlatformCompanyBillingPage.shadowedToggle', {
                                count: item.shadowed.length,
                              })}
                            </Button>
                          )}
                        </Stack>
                        <Collapse in={expanded === item.metric_code}>
                          <Stack sx={{ mt: 1 }} spacing={0.5}>
                            {item.shadowed.map((shadow) => (
                              <Typography
                                key={shadow.rate_id}
                                variant="caption"
                                color="text.secondary"
                              >
                                {t('PlatformCompanyBillingPage.shadowedRow', {
                                  scope: t(`PlatformCompanyBillingPage.source.${shadow.scope}`),
                                  amount: shadow.unit_amount,
                                })}
                              </Typography>
                            ))}
                          </Stack>
                        </Collapse>
                      </TableCell>
                      <TableCell>{formatDate(item.effective_from)}</TableCell>
                      <TableCell>
                        {item.effective_until
                          ? formatDate(item.effective_until)
                          : t('PlatformCompanyBillingPage.openEnded')}
                      </TableCell>
                      <TableCell align="right">
                        <Button size="small" disabled={readOnly} onClick={() => setEditing(item)}>
                          {t('PlatformCompanyBillingPage.overrideButton')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      {/* --- Resolver preview ---------------------------------------- */}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('PlatformCompanyBillingPage.previewTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('PlatformCompanyBillingPage.previewSubtitle')}
              </Typography>
            </Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                select
                label={t('PlatformCompanyBillingPage.previewMetric')}
                value={previewMetric}
                onChange={(event) => setPreviewMetric(event.target.value)}
                sx={{ minWidth: 220 }}
              >
                {data.items.map((item) => (
                  <MenuItem key={item.metric_code} value={item.metric_code}>
                    {metricName(t, item)}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label={t('PlatformCompanyBillingPage.previewAt')}
                type="datetime-local"
                value={previewAt}
                onChange={(event) => setPreviewAt(event.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
              />
              <Button
                variant="outlined"
                onClick={runPreview}
                disabled={!previewMetric || resolve.isPending}
                sx={{ whiteSpace: 'nowrap' }}
              >
                {t('PlatformCompanyBillingPage.previewRun')}
              </Button>
            </Stack>
            {resolve.isError && (
              <Alert severity="error">{t('PlatformCompanyBillingPage.previewFailed')}</Alert>
            )}
            {/* Rendered straight from the resolver's reply. The unpriced
                case carries the resolver's own reason, which is the
                useful part — "no price applies" without saying why sends
                somebody hunting through effective dates by hand. */}
            {preview?.priced[0] && (
              <Alert severity="success" icon={false}>
                <Typography variant="body2">
                  {t('PlatformCompanyBillingPage.previewResult', {
                    amount: preview.priced[0].unit_amount,
                    currency: preview.priced[0].currency,
                    unit: unitFor(data.items, preview.priced[0].metric_code),
                    source: t(`PlatformCompanyBillingPage.source.${preview.priced[0].scope}`),
                  })}
                </Typography>
              </Alert>
            )}
            {preview?.unpriced[0] && (
              <Alert severity="warning">
                <Typography variant="body2">
                  {t('PlatformCompanyBillingPage.previewNoPrice')}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {preview.unpriced[0].reason}
                </Typography>
              </Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* --- Audit trail --------------------------------------------- */}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={1.5}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('PlatformCompanyBillingPage.historyTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('PlatformCompanyBillingPage.historySubtitle')}
              </Typography>
            </Box>
            {(history.data ?? []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('PlatformCompanyBillingPage.historyEmpty')}
              </Typography>
            ) : (
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('PlatformCompanyBillingPage.colWhen')}</TableCell>
                      <TableCell>{t('PlatformCompanyBillingPage.colChange')}</TableCell>
                      <TableCell>{t('PlatformCompanyBillingPage.colMetric')}</TableCell>
                      <TableCell align="right">{t('PlatformCompanyBillingPage.colWas')}</TableCell>
                      <TableCell align="right">
                        {t('PlatformCompanyBillingPage.colBecame')}
                      </TableCell>
                      <TableCell>{t('PlatformCompanyBillingPage.colEffective')}</TableCell>
                      <TableCell>{t('PlatformCompanyBillingPage.colWho')}</TableCell>
                      <TableCell>{t('PlatformCompanyBillingPage.colReason')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(history.data ?? []).map((entry) => (
                      <TableRow key={entry.id} hover>
                        <TableCell>{new Date(entry.occurred_at).toLocaleString()}</TableCell>
                        <TableCell>{entry.action}</TableCell>
                        <TableCell>{entry.metric_code ?? '—'}</TableCell>
                        <TableCell align="right">
                          <Amount value={entry.old_unit_amount} currency={entry.currency} />
                        </TableCell>
                        <TableCell align="right">
                          <Amount value={entry.new_unit_amount} currency={entry.currency} />
                        </TableCell>
                        <TableCell>{formatDate(entry.effective_from)}</TableCell>
                        <TableCell>
                          {entry.changed_by_email ?? t('PlatformCompanyBillingPage.systemActor')}
                        </TableCell>
                        <TableCell>{entry.reason ?? '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </Stack>
        </CardContent>
      </Card>

      {editing && (
        <OverrideDialog
          companyId={companyId}
          item={editing}
          currency={data.currency}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  )
}

function ProfileAssignment({
  companyId,
  currentProfileId,
  currentProfileName,
  profiles,
  readOnly,
  onAssign,
  pending,
  failed,
}: {
  companyId: string
  currentProfileId: string | null
  currentProfileName: string | null
  profiles: { id: string; name: string; is_active: boolean }[]
  readOnly: boolean
  onAssign: (input: {
    companyId: string
    profile_id: string | null
    effective_from: string
    reason: string
  }) => void
  pending: boolean
  failed: boolean
}) {
  const { t } = useTranslation('platform')
  const [profileId, setProfileId] = useState(currentProfileId ?? '')
  const [reason, setReason] = useState('')

  const changed = (profileId || null) !== currentProfileId

  return (
    <Stack spacing={2}>
      <Typography variant="body2">
        {t('PlatformCompanyBillingPage.currentProfile', {
          name: currentProfileName ?? t('PlatformCompanyBillingPage.noProfile'),
        })}
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField
          select
          label={t('PlatformCompanyBillingPage.profileLabel')}
          value={profileId}
          onChange={(event) => setProfileId(event.target.value)}
          disabled={readOnly}
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">{t('PlatformCompanyBillingPage.noProfile')}</MenuItem>
          {profiles
            .filter((profile) => profile.is_active)
            .map((profile) => (
              <MenuItem key={profile.id} value={profile.id}>
                {profile.name}
              </MenuItem>
            ))}
        </TextField>
        <TextField
          label={t('PlatformCompanyBillingPage.reasonLabel')}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={readOnly}
          fullWidth
          // Required by the API, and rightly so: "why is this customer on
          // the Enterprise profile" is exactly the question asked six
          // months later.
          helperText={t('PlatformCompanyBillingPage.reasonHelp')}
        />
        <Button
          variant="contained"
          disabled={readOnly || !changed || !reason.trim() || pending}
          onClick={() =>
            onAssign({
              companyId,
              profile_id: profileId || null,
              effective_from: new Date().toISOString(),
              reason: reason.trim(),
            })
          }
          sx={{ whiteSpace: 'nowrap' }}
        >
          {t('PlatformCompanyBillingPage.assignButton')}
        </Button>
      </Stack>
      {failed && <Alert severity="error">{t('PlatformCompanyBillingPage.assignFailed')}</Alert>}
    </Stack>
  )
}

function OverrideDialog({
  companyId,
  item,
  currency,
  onClose,
}: {
  companyId: string
  item: EffectivePrice
  currency: string
  onClose: () => void
}) {
  const { t } = useTranslation('platform')
  const setRate = useSetCompanyRateMutation()
  const [amount, setAmount] = useState(item.unit_amount ?? '')
  const [reason, setReason] = useState('')

  const alreadyCompanyScoped = item.scope === 'company'

  const submit = () => {
    setRate.mutate(
      {
        companyId,
        metricCode: item.metric_code,
        unit_amount: amount.trim(),
        // "Now", which the engine accepts within a one-minute grace
        // window — by the time it validates, the client's "now" is
        // already a moment in the past.
        effective_from: new Date().toISOString(),
        reason: reason.trim(),
        // The company's own currency. A rate priced in anything else is
        // invisible to resolution for this company.
        currency,
        // Optimistic concurrency: send the rate we are replacing, or say
        // there wasn't one. Without it, two operators editing the same
        // price both succeed and the second silently wins.
        ...(alreadyCompanyScoped && item.rate_id
          ? { expected_current_rate_id: item.rate_id }
          : { expect_no_current_rate: true }),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>
        {t('PlatformCompanyBillingPage.overrideTitle', { metric: metricName(t, item) })}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="info">
            {alreadyCompanyScoped
              ? t('PlatformCompanyBillingPage.overrideReplacing')
              : t('PlatformCompanyBillingPage.overrideCreating', {
                  source: t(`PlatformCompanyBillingPage.source.${item.scope ?? 'global'}`),
                })}
          </Alert>
          <TextField
            label={t('PlatformCompanyBillingPage.overrideAmount', { currency })}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            required
            fullWidth
            // Text, not number: a number input would hand the value to
            // the browser's float parsing, and a price is a decimal.
            // `inputMode` has to go through slotProps to reach the real
            // <input> — set on the TextField it is silently dropped, and
            // a phone shows a full keyboard instead of a numeric pad.
            slotProps={{ htmlInput: { inputMode: 'decimal' } }}
            helperText={t('PlatformCompanyBillingPage.overrideAmountHelp')}
          />
          <TextField
            label={t('PlatformCompanyBillingPage.reasonLabel')}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required
            fullWidth
            multiline
            minRows={2}
            helperText={t('PlatformCompanyBillingPage.overrideReasonHelp')}
          />
          {setRate.isError && (
            <Alert severity="error">{t('PlatformCompanyBillingPage.overrideFailed')}</Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button color="inherit" onClick={onClose}>
          {t('PlatformCompanyBillingPage.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={submit}
          disabled={!amount.trim() || !reason.trim() || setRate.isPending}
        >
          {t('PlatformCompanyBillingPage.overrideSave')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
