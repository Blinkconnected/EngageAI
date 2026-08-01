import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { usePaymentProvidersQuery, useSavePaymentProviderMutation } from './api'
import type { PaymentProvider, ProviderReadiness } from './types'

const READINESS_COLOUR: Record<ProviderReadiness, 'success' | 'default' | 'warning'> = {
  active: 'success',
  not_configured: 'default',
  awaiting_integration: 'warning',
}

/** One provider's card.
 *
 * Each provider is its own form and its own save. These are separate
 * contracts with separate people — a single form that saved all of them at
 * once would make editing one an opportunity to clear another. */
function ProviderCard({ provider }: { provider: PaymentProvider }) {
  const { t } = useTranslation('platform')
  const save = useSavePaymentProviderMutation()

  /** Edits held as an overlay on the loaded provider rather than copied in
   * by an effect — the same reasoning as the mail page. Copying would need
   * a setState-in-effect to resync after each save, and would drop an edit
   * made while the request was in flight. */
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [enabled, setEnabled] = useState<boolean | null>(null)

  const isEnabled = enabled ?? provider.enabled
  const dirty = Object.keys(edits).length > 0 || enabled !== null

  const valueOf = (name: string): string => {
    if (name in edits) return edits[name]
    const stored = provider.values[name]
    return stored === undefined || stored === null ? '' : String(stored)
  }

  const handleSave = () => {
    /** Only what was actually edited is sent. A secret the operator did not
     * retype is therefore absent, which the API reads as "unchanged" — send
     * the whole form back and every untouched credential would be
     * overwritten with the blank the screen was given. */
    const values: Record<string, unknown> = { ...edits }
    for (const field of provider.fields) {
      if (field.name === 'sandbox' && field.name in edits) {
        values.sandbox = edits.sandbox === 'true'
      }
    }
    save.mutate(
      { kind: provider.kind, input: { enabled: isEnabled, values } },
      { onSuccess: () => { setEdits({}); setEnabled(null) } },
    )
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {provider.label}
          </Typography>
          <Chip
            size="small"
            label={t(`payments.flow.${provider.flow}`)}
            variant="outlined"
          />
          <Chip
            size="small"
            color={READINESS_COLOUR[provider.readiness]}
            label={t(`payments.readiness.${provider.readiness}`)}
          />
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {provider.description}
        </Typography>

        {/* Said plainly rather than hidden. An operator entering credentials
            for a scheme that cannot yet take payments needs to know that
            now, not after a customer cannot pay. */}
        {provider.readiness === 'awaiting_integration' && provider.pending_note ? (
          <Alert severity="info" sx={{ mt: 2 }}>
            {provider.pending_note}
          </Alert>
        ) : null}

        {provider.fields.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {t('payments.noConfiguration')}
          </Typography>
        ) : (
          <>
            <Divider sx={{ my: 2 }} />
            <Stack spacing={2}>
              {provider.fields.map((field) => {
                const isSet = provider.secret_set[field.name]
                const missing = provider.missing.includes(field.name)

                if (field.name === 'sandbox') {
                  return (
                    <FormControlLabel
                      key={field.name}
                      control={
                        <Switch
                          checked={valueOf('sandbox') !== 'false'}
                          onChange={(event) =>
                            setEdits((current) => ({
                              ...current,
                              sandbox: String(event.target.checked),
                            }))
                          }
                        />
                      }
                      label={field.label}
                    />
                  )
                }

                return (
                  <TextField
                    key={field.name}
                    label={field.label}
                    value={valueOf(field.name)}
                    required={field.required}
                    error={missing}
                    select={field.choices.length > 0}
                    type={field.secret ? 'password' : 'text'}
                    /* A stored secret is never sent to this screen, so the
                       box is empty for a credential that exists. Saying so
                       stops an operator retyping a working password merely
                       because the field looks blank. */
                    placeholder={
                      field.secret && isSet ? t('payments.secretSet') : undefined
                    }
                    helperText={
                      field.secret && isSet
                        ? t('payments.secretKeepHint')
                        : (field.help_text ?? undefined)
                    }
                    onChange={(event) =>
                      setEdits((current) => ({
                        ...current,
                        [field.name]: event.target.value,
                      }))
                    }
                    fullWidth
                    size="small"
                  >
                    {field.choices.map((choice) => (
                      <MenuItem key={choice} value={choice}>
                        {choice}
                      </MenuItem>
                    ))}
                  </TextField>
                )
              })}
            </Stack>
          </>
        )}

        <Divider sx={{ my: 2 }} />
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <FormControlLabel
            control={
              <Switch
                checked={isEnabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
            }
            label={t('payments.enabled')}
          />
          <Box sx={{ flexGrow: 1 }} />
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={!dirty || save.isPending}
          >
            {t('payments.save')}
          </Button>
        </Stack>

        {save.isError ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {t('payments.saveFailed')}
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function PlatformPaymentProvidersPage() {
  const { t } = useTranslation('platform')
  const query = usePaymentProvidersQuery()

  if (query.isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (query.isError || !query.data) {
    return <Alert severity="error">{t('payments.loadFailed')}</Alert>
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5">{t('payments.title')}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {t('payments.subtitle')}
        </Typography>
      </Box>

      {query.data.updated_by_email ? (
        <Typography variant="caption" color="text.secondary">
          {t('payments.lastChangedBy', { email: query.data.updated_by_email })}
        </Typography>
      ) : null}

      {query.data.providers.map((provider) => (
        <ProviderCard key={provider.kind} provider={provider} />
      ))}
    </Stack>
  )
}
