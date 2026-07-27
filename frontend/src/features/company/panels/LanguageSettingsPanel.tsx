import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  CardContent,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { SUPPORTED_I18N_LANGUAGES } from '../../../i18n'
import { useUpdateCompanyMutation } from '../api'
import { LANGUAGE_LABELS, type Company, type SupportedLanguage } from '../types'

export function LanguageSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettings')
  const [language, setLanguage] = useState<SupportedLanguage>(company.settings.language ?? 'en')
  const updateMutation = useUpdateCompanyMutation()
  const savedLanguage = company.settings.language ?? 'en'
  const isDirty = language !== savedLanguage

  function handleSave() {
    // Applying the new language/direction is handled by `useLanguageSync`
    // (mounted once in AppLayout), which reacts to `company.settings
    // .language` changing in the query cache — not here — so the "Saved"
    // confirmation below still renders in the language you were just
    // using, and the app transitions right after, instead of racing this
    // save handler against this very alert's own re-render.
    updateMutation.mutate({ settings: { language } })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('LanguageSettingsPanel.description')}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('LanguageSettingsPanel.savedMessage')}</Alert>
          )}

          <TextField
            select
            label={t('LanguageSettingsPanel.defaultLanguageLabel')}
            value={language}
            onChange={(event) => setLanguage(event.target.value as SupportedLanguage)}
            fullWidth
            helperText={t('LanguageSettingsPanel.defaultLanguageHelperText')}
          >
            {SUPPORTED_I18N_LANGUAGES.map((code) => (
              <MenuItem key={code} value={code}>
                {LANGUAGE_LABELS[code]}
              </MenuItem>
            ))}
          </TextField>

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('LanguageSettingsPanel.savingButton')
              : t('LanguageSettingsPanel.saveChangesButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
