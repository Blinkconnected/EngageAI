import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import {
  useCreatePlanMutation,
  useFeatureCatalogQuery,
  usePlatformPlansQuery,
  useSetPlanStatusMutation,
} from './api'
import type { BillingInterval, BillingPlan } from './types'

/**
 * The platform's price list.
 *
 * Creating a plan publishes it to PayPal, which is why price and
 * interval cannot be edited afterwards: PayPal treats a plan's billing
 * cycle as fixed, and letting an operator change the local price while
 * PayPal keeps charging the old one would bill customers an amount the
 * product never showed them. Repricing means publishing a new plan.
 */
export function PlatformPlansPage() {
  const { t } = useTranslation('platform')
  const plansQuery = usePlatformPlansQuery()
  const catalogQuery = useFeatureCatalogQuery()
  const createMutation = useCreatePlanMutation()
  const statusMutation = useSetPlanStatusMutation()

  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [interval, setInterval] = useState<BillingInterval>('month')
  const [restrictFeatures, setRestrictFeatures] = useState(false)
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([])

  function resetForm() {
    setName('')
    setDescription('')
    setAmount('')
    setCurrency('USD')
    setInterval('month')
    setRestrictFeatures(false)
    setSelectedFeatures([])
  }

  function handleCreate() {
    setError(null)
    createMutation.mutate(
      {
        name,
        description: description || null,
        amount,
        currency,
        interval,
        // null grants everything; a list restricts to exactly it.
        features: restrictFeatures ? selectedFeatures : null,
      },
      {
        onSuccess: () => {
          setIsCreating(false)
          resetForm()
        },
        onError: (mutationError) =>
          setError(extractErrorMessage(mutationError, t('PlatformPlansPage.createError'))),
      },
    )
  }

  function toggleFeature(key: string) {
    setSelectedFeatures((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    )
  }

  function featureSummary(plan: BillingPlan): string {
    if (plan.features === null) return t('PlatformPlansPage.allFeatures')
    if (plan.features.length === 0) return t('PlatformPlansPage.noFeatures')
    const names = plan.features.map(
      (key) => catalogQuery.data?.find((feature) => feature.key === key)?.name ?? key,
    )
    return names.join(', ')
  }

  return (
    <>
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
        {t('PlatformPlansPage.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('PlatformPlansPage.description')}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Button variant="contained" sx={{ mb: 2 }} onClick={() => setIsCreating(true)}>
        {t('PlatformPlansPage.newPlan')}
      </Button>

      {plansQuery.isPending && <CircularProgress size={24} />}
      {plansQuery.isError && (
        <Alert
          severity="error"
          action={
            <Button size="small" onClick={() => void plansQuery.refetch()}>
              {t('PlatformPlansPage.retry')}
            </Button>
          }
        >
          {t('PlatformPlansPage.loadError')}
        </Alert>
      )}

      {plansQuery.data?.length === 0 && (
        <EmptyState
          title={t('PlatformPlansPage.emptyTitle')}
          description={t('PlatformPlansPage.emptyDescription')}
        />
      )}

      <Stack spacing={2}>
        {(plansQuery.data ?? []).map((plan) => (
          <Card key={plan.id} variant="outlined">
            <CardContent>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={2}
                sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' } }}
              >
                <Box>
                  <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.5 }}>
                    <Typography variant="h6" component="h2">
                      {plan.name}
                    </Typography>
                    <Chip
                      size="small"
                      color={plan.is_active ? 'success' : 'default'}
                      label={t(
                        `PlatformPlansPage.${plan.is_active ? 'activeChip' : 'withdrawnChip'}`,
                      )}
                    />
                    {!plan.is_purchasable && plan.is_active && (
                      <Chip
                        size="small"
                        color="warning"
                        label={t('PlatformPlansPage.notPublishedChip')}
                      />
                    )}
                  </Stack>
                  <Typography variant="body1">
                    {plan.currency} {plan.amount} /{' '}
                    {t(`PlatformPlansPage.interval.${plan.interval}`)}
                  </Typography>
                  {plan.description && (
                    <Typography variant="body2" color="text.secondary">
                      {plan.description}
                    </Typography>
                  )}
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    {t('PlatformPlansPage.includes', { features: featureSummary(plan) })}
                  </Typography>
                </Box>
                <Button
                  size="small"
                  variant="outlined"
                  color={plan.is_active ? 'error' : 'success'}
                  disabled={statusMutation.isPending}
                  onClick={() =>
                    statusMutation.mutate({ planId: plan.id, isActive: !plan.is_active })
                  }
                >
                  {t(`PlatformPlansPage.${plan.is_active ? 'withdrawButton' : 'restoreButton'}`)}
                </Button>
              </Stack>
            </CardContent>
          </Card>
        ))}
      </Stack>

      <Dialog open={isCreating} onClose={() => setIsCreating(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('PlatformPlansPage.newPlan')}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('PlatformPlansPage.nameLabel')}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label={t('PlatformPlansPage.descriptionLabel')}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              multiline
              minRows={2}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label={t('PlatformPlansPage.amountLabel')}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                required
                sx={{ flex: 1 }}
              />
              <TextField
                label={t('PlatformPlansPage.currencyLabel')}
                value={currency}
                onChange={(event) => setCurrency(event.target.value.toUpperCase())}
                slotProps={{ htmlInput: { maxLength: 3 } }}
                sx={{ width: 110 }}
              />
              <TextField
                select
                label={t('PlatformPlansPage.intervalLabel')}
                value={interval}
                onChange={(event) => setInterval(event.target.value as BillingInterval)}
                sx={{ width: 140 }}
              >
                <MenuItem value="month">{t('PlatformPlansPage.interval.month')}</MenuItem>
                <MenuItem value="year">{t('PlatformPlansPage.interval.year')}</MenuItem>
              </TextField>
            </Stack>
            <Alert severity="info">{t('PlatformPlansPage.priceIsFinal')}</Alert>

            <FormControlLabel
              control={
                <Checkbox
                  checked={restrictFeatures}
                  onChange={(event) => setRestrictFeatures(event.target.checked)}
                />
              }
              label={t('PlatformPlansPage.restrictFeatures')}
            />
            {restrictFeatures && (
              <Stack sx={{ pl: 1 }}>
                {(catalogQuery.data ?? []).map((feature) => (
                  <FormControlLabel
                    key={feature.key}
                    control={
                      <Checkbox
                        checked={selectedFeatures.includes(feature.key)}
                        onChange={() => toggleFeature(feature.key)}
                      />
                    }
                    label={feature.name}
                  />
                ))}
              </Stack>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsCreating(false)}>{t('PlatformPlansPage.cancel')}</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={createMutation.isPending || !name || !amount}
          >
            {t('PlatformPlansPage.create')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
