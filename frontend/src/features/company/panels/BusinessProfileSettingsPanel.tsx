import { useState, type FormEvent } from 'react'
import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { BusinessProfileSettings, Company } from '../types'

/** The fields, in the order they reach the AI prompt. Keeping the order
 * here identical to the backend's `BUSINESS_PROFILE_FIELDS` means what an
 * administrator reads on this screen is what the model reads. */
const FIELDS = [
  { key: 'legal_name', multiline: false },
  { key: 'location', multiline: true },
  { key: 'contact', multiline: true },
  { key: 'website', multiline: false },
  { key: 'about', multiline: true },
] as const

type FieldKey = (typeof FIELDS)[number]['key']

function initialValues(company: Company): Record<FieldKey, string> {
  const stored = company.settings.business_profile ?? {}
  return {
    legal_name: stored.legal_name ?? '',
    location: stored.location ?? '',
    contact: stored.contact ?? '',
    website: stored.website ?? '',
    about: stored.about ?? '',
  }
}

/** Blank fields are dropped rather than sent as empty strings.
 *
 * This is the whole point of the screen, not a tidiness detail. A field
 * the administrator left empty must be *absent* from the AI prompt: a
 * model shown a labelled blank fills it in, which is how this company's
 * Autopilot came to announce opening hours nobody had ever configured. */
function toPayload(values: Record<FieldKey, string>): BusinessProfileSettings {
  const payload: BusinessProfileSettings = {}
  for (const { key } of FIELDS) {
    const trimmed = values[key].trim()
    if (trimmed) payload[key] = trimmed
  }
  return payload
}

export function BusinessProfileSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
  const [values, setValues] = useState(() => initialValues(company))
  const updateMutation = useUpdateCompanyMutation()

  const saved = initialValues(company)
  const isDirty = FIELDS.some(({ key }) => values[key].trim() !== saved[key].trim())

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateMutation.mutate({ settings: { business_profile: toPayload(values) } })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 620 }}>
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="body2" color="text.secondary">
            {t('BusinessProfileSettingsPanel.description')}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('BusinessProfileSettingsPanel.savedMessage')}</Alert>
          )}

          {FIELDS.map(({ key, multiline }) => (
            <TextField
              key={key}
              label={t(`BusinessProfileSettingsPanel.${key}Label`)}
              helperText={t(`BusinessProfileSettingsPanel.${key}Helper`)}
              value={values[key]}
              onChange={(event) => setValues((prev) => ({ ...prev, [key]: event.target.value }))}
              multiline={multiline}
              minRows={multiline ? 2 : undefined}
              fullWidth
            />
          ))}

          <Alert severity="info">{t('BusinessProfileSettingsPanel.hoursNotice')}</Alert>

          <Button
            type="submit"
            variant="contained"
            disabled={updateMutation.isPending || !isDirty}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('BusinessProfileSettingsPanel.savingButton')
              : t('BusinessProfileSettingsPanel.saveChangesButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
