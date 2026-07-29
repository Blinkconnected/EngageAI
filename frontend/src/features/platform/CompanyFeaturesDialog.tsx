import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCompanyFeaturesQuery, useSetCompanyFeaturesMutation } from './api'
import type { CompanyOverview, FeatureState } from './types'

interface Props {
  company: CompanyOverview | null
  onClose: () => void
}

/**
 * Which product features one company may use.
 *
 * Shows each feature's *source* alongside its state, because a disabled
 * feature is fixed differently depending on why it is disabled: change
 * the plan, or clear the override. A switch here always writes an
 * override — the explicit, per-company decision — and "Follow plan"
 * removes it again.
 */
export function CompanyFeaturesDialog({ company, onClose }: Props) {
  const { t } = useTranslation('platform')
  const featuresQuery = useCompanyFeaturesQuery(company?.id ?? null)
  const mutation = useSetCompanyFeaturesMutation()
  const [pendingOverrides, setPendingOverrides] = useState<Record<string, boolean> | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Derived, not synced in an effect: the server's answer is the source
  // of truth until the operator actually changes something.
  const overrides = useMemo(() => {
    if (pendingOverrides !== null) return pendingOverrides
    const fromServer: Record<string, boolean> = {}
    for (const state of featuresQuery.data ?? []) {
      if (state.source === 'override') fromServer[state.key] = state.enabled
    }
    return fromServer
  }, [pendingOverrides, featuresQuery.data])

  function resolvedState(state: FeatureState): boolean {
    return state.key in overrides ? overrides[state.key] : state.enabled
  }

  function toggle(state: FeatureState) {
    setPendingOverrides({ ...overrides, [state.key]: !resolvedState(state) })
  }

  function followPlan(state: FeatureState) {
    const next = { ...overrides }
    delete next[state.key]
    setPendingOverrides(next)
  }

  function handleClose() {
    setPendingOverrides(null)
    setError(null)
    onClose()
  }

  function handleSave() {
    if (!company) return
    setError(null)
    mutation.mutate(
      { companyId: company.id, overrides },
      {
        onSuccess: handleClose,
        onError: (mutationError) =>
          setError(extractErrorMessage(mutationError, t('CompanyFeaturesDialog.saveError'))),
      },
    )
  }

  return (
    <Dialog open={company !== null} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('CompanyFeaturesDialog.title', { companyName: company?.name ?? '' })}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('CompanyFeaturesDialog.description')}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {featuresQuery.isPending && <CircularProgress size={24} />}
        {featuresQuery.isError && (
          <Alert severity="error">{t('CompanyFeaturesDialog.loadError')}</Alert>
        )}

        <Stack spacing={1.5}>
          {(featuresQuery.data ?? []).map((state) => {
            const overridden = state.key in overrides
            return (
              <Stack
                key={state.key}
                direction="row"
                spacing={2}
                sx={{ alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div>
                  <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                    <Typography variant="body1">{state.name}</Typography>
                    <Chip
                      size="small"
                      variant="outlined"
                      label={t(
                        `CompanyFeaturesDialog.source.${overridden ? 'override' : state.source}`,
                      )}
                    />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {state.description}
                  </Typography>
                </div>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexShrink: 0 }}>
                  {overridden && (
                    <Button size="small" onClick={() => followPlan(state)}>
                      {t('CompanyFeaturesDialog.followPlan')}
                    </Button>
                  )}
                  <Switch
                    checked={resolvedState(state)}
                    onChange={() => toggle(state)}
                    slotProps={{ input: { 'aria-label': state.name } }}
                  />
                </Stack>
              </Stack>
            )
          })}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('CompanyFeaturesDialog.cancel')}</Button>
        <Button variant="contained" onClick={handleSave} disabled={mutation.isPending}>
          {t('CompanyFeaturesDialog.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
