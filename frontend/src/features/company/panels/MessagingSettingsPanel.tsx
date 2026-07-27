import { useState } from 'react'
import {
  Alert,
  Card,
  CardContent,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

export function MessagingSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
  const [typingIndicatorEnabled, setTypingIndicatorEnabled] = useState(
    company.settings.messaging?.typing_indicator_enabled ?? true,
  )
  const updateMutation = useUpdateCompanyMutation()

  function handleChange(enabled: boolean) {
    setTypingIndicatorEnabled(enabled)
    updateMutation.mutate(
      { settings: { messaging: { typing_indicator_enabled: enabled } } },
      { onError: () => setTypingIndicatorEnabled(!enabled) },
    )
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}

          <FormControlLabel
            control={
              <Switch
                checked={typingIndicatorEnabled}
                onChange={(event) => handleChange(event.target.checked)}
              />
            }
            label={t('MessagingSettingsPanel.typingIndicatorLabel')}
          />
          <Typography variant="body2" color="text.secondary">
            {t('MessagingSettingsPanel.description')}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}
