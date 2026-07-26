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
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

export function MessagingSettingsPanel({ company }: { company: Company }) {
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
            label="Show agents' typing indicator to customers"
          />
          <Typography variant="body2" color="text.secondary">
            When on, customers see a live "agent is typing…" indicator on channels that support
            it (Web Chat, WhatsApp, Telegram).
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}
