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
  // `?? ''` also absorbs the explicit nulls a clear-and-save writes.
  return {
    legal_name: stored.legal_name ?? '',
    location: stored.location ?? '',
    contact: stored.contact ?? '',
    website: stored.website ?? '',
    about: stored.about ?? '',
  }
}

/** A cleared field is sent as an explicit `null`, never omitted.
 *
 * `CompanyService._merge_settings` merges a section one level deep, so
 * every field this payload leaves out keeps whatever was stored before.
 * Omitting blanks would therefore make *clearing* a field impossible: an
 * administrator could delete the address, save, be told it saved, and
 * have AI carry on quoting the old one. Sending `null` overwrites it,
 * and the backend reader (`domain.company_settings.business_profile`)
 * drops non-string values — so a nulled field is absent from the AI
 * prompt, which is the state a blank is meant to produce. */
function toPayload(values: Record<FieldKey, string>): BusinessProfileSettings {
  const payload: BusinessProfileSettings = {}
  for (const { key } of FIELDS) {
    const trimmed = values[key].trim()
    payload[key] = trimmed || null
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
