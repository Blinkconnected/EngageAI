import { useState } from 'react'
import { Alert, Button, Card, CardContent, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, type Company, type SupportedLanguage } from '../types'

export function LanguageSettingsPanel({ company }: { company: Company }) {
  const [language, setLanguage] = useState<SupportedLanguage>(company.settings.language ?? 'en')
  const updateMutation = useUpdateCompanyMutation()
  const savedLanguage = company.settings.language ?? 'en'

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Your company's default language. Full interface translation is coming in a future
            update — this sets the preference for when it arrives.
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && <Alert severity="success">Saved.</Alert>}

          <TextField
            select
            label="Default language"
            value={language}
            onChange={(event) => setLanguage(event.target.value as SupportedLanguage)}
            fullWidth
          >
            {SUPPORTED_LANGUAGES.map((code) => (
              <MenuItem key={code} value={code}>
                {LANGUAGE_LABELS[code]}
              </MenuItem>
            ))}
          </TextField>

          <Button
            variant="contained"
            disabled={updateMutation.isPending || language === savedLanguage}
            onClick={() => updateMutation.mutate({ settings: { language } })}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
