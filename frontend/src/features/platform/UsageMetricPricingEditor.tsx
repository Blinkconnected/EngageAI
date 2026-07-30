import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { useQuotePricingMutation, useSetPriceMutation } from './api'
import { TierTableEditor } from './TierTableEditor'
import { tableFrom } from './tierTable'
import { metricName } from './metricName'
import type {
  BillableMetric,
  EffectivePrice,
  PricingModel,
  PricingModelInfo,
  PricingQuote,
  Tier,
} from './types'

/** What the preview asks for. A round number an operator can reason about,
 * and one that lands past the first tier boundary of the shipped table so a
 * tiered rate visibly differs from a flat one. */
const PREVIEW_QUANTITY = '300'

/** An amount exactly as the server sent it, with the currency it said.
 *
 * Deliberately not `Intl.NumberFormat` on a parsed float — the same reason as
 * on the company billing screen: JOD has three decimal places and USD two,
 * the API already returns the value at the right scale, and re-formatting a
 * parsed number is how a displayed price stops matching the billed one. */
function amount(value: string, currency: string): string {
  return `${value} ${currency}`
}

export interface PricingDraft {
  model: PricingModel
  unitAmount: string
  tiers: Tier[]
  includedQuantity: string
  minimumCharge: string
  reason: string
}

function draftFrom(price: EffectivePrice): PricingDraft {
  return {
    model: 'flat',
    unitAmount: price.unit_amount ?? '',
    tiers: tableFrom(price.unit_amount ?? ''),
    includedQuantity: '',
    minimumCharge: '',
    reason: '',
  }
}

/**
 * Editing what one usage metric costs.
 *
 * Generic on purpose: the metric is a parameter, and every field comes from
 * what the *server* says the metric and the models are. Nothing here knows
 * that messages exist, so the day a token or a phone-minute meter ships, this
 * screen prices it with no change.
 *
 * **The preview is computed by the pricing engine, never here.** A tier table
 * applied in TypeScript would eventually disagree with the invoice, and the
 * preview is exactly where an operator decides a price is right — so it asks
 * the server what these terms would charge and shows that answer.
 */
export function UsageMetricPricingEditor({
  price,
  metric,
  models,
  currency,
  profileId,
  onClose,
}: {
  price: EffectivePrice
  metric: BillableMetric | undefined
  models: PricingModelInfo[]
  currency: string
  profileId: string | undefined
  onClose: () => void
}) {
  const { t } = useTranslation('platform')
  const setPrice = useSetPriceMutation()
  const quote = useQuotePricingMutation()

  // The server's `display_name`/`description` are English prose; `model` is a
  // stable code. Translating from the code and falling back to what the
  // server said means an Arabic operator reads Arabic, while a model added
  // server-side before its translation exists still reads as English prose
  // rather than a missing-key placeholder.
  const name = (option: PricingModelInfo) =>
    t(`PricingModels.${option.model}.name`, option.display_name)
  const describe = (option: PricingModelInfo) =>
    t(`PricingModels.${option.model}.description`, option.description)

  const [draft, setDraft] = useState<PricingDraft>(() => draftFrom(price))
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PricingQuote | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const selected = models.find((option) => option.model === draft.model)
  const needsTiers = selected?.requires_tiers ?? false

  // Everything the preview depends on, as one string: a stable trigger that
  // does not re-quote on every keystroke of the *reason* field.
  const termsKey = useMemo(
    () =>
      JSON.stringify([
        draft.model,
        draft.unitAmount,
        draft.tiers,
        draft.includedQuantity,
        draft.minimumCharge,
      ]),
    [draft.model, draft.unitAmount, draft.tiers, draft.includedQuantity, draft.minimumCharge],
  )

  useEffect(() => {
    // Debounced, because an operator typing "0.0015" would otherwise ask the
    // server six questions and see five wrong answers on the way.
    const timer = setTimeout(() => {
      const terms = JSON.parse(termsKey) as [PricingModel, string, Tier[], string, string]
      const [model, unitAmount, tiers, included, minimum] = terms
      if (!unitAmount && !tiers.some((tier) => tier.unit_amount)) {
        setPreview(null)
        setPreviewError(null)
        return
      }
      quote.mutate(
        {
          metricCode: price.metric_code,
          currency,
          quantity: PREVIEW_QUANTITY,
          pricingModel: model,
          unitAmount: unitAmount || tiers[tiers.length - 1]?.unit_amount || '0',
          ...(model === 'volume_tier' || model === 'graduated_tier' ? { tiers } : {}),
          includedQuantity: included || null,
          minimumCharge: minimum || null,
        },
        {
          onSuccess: (result) => {
            setPreview(result)
            setPreviewError(null)
          },
          onError: (quoteError) => {
            // Shown rather than swallowed: the server's refusal *is* the
            // validation message, and seeing it while typing beats
            // discovering it on save.
            setPreview(null)
            setPreviewError(extractErrorMessage(quoteError, t('PricingEditor.previewError')))
          },
        },
      )
    }, 400)
    return () => clearTimeout(timer)
    // `quote` is a stable mutation object; including it would re-run on every
    // render. `t` only changes with the language, which does not affect what
    // is asked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [termsKey, price.metric_code, currency])

  function handleModelChange(model: PricingModel) {
    setDraft((current) => ({
      ...current,
      model,
      // Switching to a tiered model seeds a one-step table carrying the rate
      // they already had, so changing the *shape* does not silently change
      // the price.
      tiers: current.tiers.length ? current.tiers : tableFrom(current.unitAmount),
    }))
  }

  function handleSave() {
    setError(null)
    setPrice.mutate(
      {
        metricCode: price.metric_code,
        pricingModel: draft.model,
        unitAmount:
          draft.model === 'flat'
            ? draft.unitAmount
            : // For a tiered rate the parent amount is the top step, so
              // anything reading a rate without its tiers still gets a real
              // price rather than nothing.
              draft.tiers[draft.tiers.length - 1]?.unit_amount || draft.unitAmount,
        ...(needsTiers ? { tiers: draft.tiers } : {}),
        includedQuantity: draft.includedQuantity || null,
        minimumCharge: draft.minimumCharge || null,
        effectiveFrom: new Date().toISOString(),
        reason: draft.reason || undefined,
        profileId: profileId || undefined,
        ...(price.rate_id
          ? { expectedCurrentRateId: price.rate_id }
          : { expectNoCurrentRate: true }),
      },
      {
        onSuccess: onClose,
        onError: (saveError) =>
          setError(extractErrorMessage(saveError, t('PricingEditor.saveError'))),
      },
    )
  }

  // The catalogue is a separate query and may not have resolved yet; the price
  // row carries its own unit, so falling back to it means the labels never
  // render as "Rate per " with the noun missing.
  const unit = metric?.unit ?? price.unit
  const unitLabel = t(`PlatformPricingPage.unit.${unit}`, unit)

  return (
    <Dialog open fullWidth maxWidth="sm" onClose={onClose}>
      <DialogTitle>
        {t('PricingEditor.title', { metric: metricName(t, price) })}
        <Typography variant="body2" color="text.secondary">
          {t('PricingEditor.subtitle', { unit: unitLabel, currency })}
        </Typography>
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          <TextField
            select
            label={t('PricingEditor.modelLabel')}
            value={draft.model}
            onChange={(event) => handleModelChange(event.target.value as PricingModel)}
            helperText={selected && describe(selected)}
          >
            {models.map((option) => (
              // Models that are not enabled stay visible and disabled: an
              // operator can see what is coming without being able to
              // configure a price that would never charge.
              <MenuItem key={option.model} value={option.model} disabled={!option.enabled}>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                  <span>{name(option)}</span>
                  {option.enabled ? null : (
                    <Chip size="small" label={t('PricingEditor.notYetAvailable')} />
                  )}
                </Stack>
              </MenuItem>
            ))}
          </TextField>

          {needsTiers ? (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                {t('PricingEditor.tiersTitle')}
              </Typography>
              <TierTableEditor
                tiers={draft.tiers}
                unitLabel={unitLabel}
                onChange={(tiers) => setDraft((current) => ({ ...current, tiers }))}
              />
            </Box>
          ) : (
            <TextField
              label={t('PricingEditor.unitAmountLabel', { unit: unitLabel })}
              value={draft.unitAmount}
              onChange={(event) =>
                setDraft((current) => ({ ...current, unitAmount: event.target.value }))
              }
              slotProps={{ htmlInput: { inputMode: 'decimal' } }}
              placeholder="0.002"
            />
          )}

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              fullWidth
              label={t('PricingEditor.includedLabel')}
              value={draft.includedQuantity}
              onChange={(event) =>
                setDraft((current) => ({ ...current, includedQuantity: event.target.value }))
              }
              slotProps={{ htmlInput: { inputMode: 'decimal' } }}
              helperText={t('PricingEditor.includedHint')}
            />
            <TextField
              fullWidth
              label={t('PricingEditor.minimumLabel')}
              value={draft.minimumCharge}
              onChange={(event) =>
                setDraft((current) => ({ ...current, minimumCharge: event.target.value }))
              }
              slotProps={{ htmlInput: { inputMode: 'decimal' } }}
              helperText={t('PricingEditor.minimumHint')}
            />
          </Stack>

          <Divider />

          {/* The preview. Computed by the pricing engine — the same function
              that prices the invoice — so what an operator approves here is
              what a customer is charged. */}
          <Box data-testid="pricing-preview">
            <Typography variant="subtitle2">
              {t('PricingEditor.previewTitle', {
                quantity: PREVIEW_QUANTITY,
                unit: unitLabel,
              })}
            </Typography>
            {previewError ? (
              <Alert severity="warning" sx={{ mt: 1 }}>
                {previewError}
              </Alert>
            ) : preview ? (
              <Stack spacing={0.5} sx={{ mt: 1 }}>
                <Typography variant="h6" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {amount(preview.subtotal, preview.currency)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t('PricingEditor.previewBreakdown', {
                    included: preview.included_quantity,
                    billable: preview.billable_quantity,
                    rate: amount(preview.unit_amount, preview.currency),
                  })}
                </Typography>
                {preview.minimum_applied && (
                  <Typography variant="caption" color="warning.main">
                    {t('PricingEditor.previewMinimumApplied')}
                  </Typography>
                )}
              </Stack>
            ) : (
              <Typography variant="caption" color="text.secondary">
                {t('PricingEditor.previewEmpty')}
              </Typography>
            )}
          </Box>

          <TextField
            label={t('PricingEditor.reasonLabel')}
            value={draft.reason}
            onChange={(event) =>
              setDraft((current) => ({ ...current, reason: event.target.value }))
            }
            multiline
            minRows={2}
            helperText={t('PricingEditor.reasonHint')}
          />

          {/* The question every operator asks before clicking save, answered
              before they have to ask it. A closed period keeps the price it
              was closed at — see the effective-dating rules in
              docs/architecture/billing.md. */}
          <Alert severity="info" icon={false}>
            {t('PricingEditor.historyNote')}
          </Alert>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('PricingEditor.cancel')}</Button>
        <Button variant="contained" onClick={handleSave} disabled={setPrice.isPending}>
          {t('PricingEditor.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
