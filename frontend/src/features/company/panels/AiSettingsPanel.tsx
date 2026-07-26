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

export function AiSettingsPanel({ company }: { company: Company }) {
  const [enabled, setEnabled] = useState(company.settings.ai?.enabled ?? true)
  const updateMutation = useUpdateCompanyMutation()

  function handleChange(next: boolean) {
    setEnabled(next)
    updateMutation.mutate(
      { settings: { ai: { enabled: next } } },
      { onError: () => setEnabled(!next) },
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
              <Switch checked={enabled} onChange={(event) => handleChange(event.target.checked)} />
            }
            label="Enable AI Engine features"
          />
          <Typography variant="body2" color="text.secondary">
            Reply suggestions, summaries, translation, sentiment, and other AI features for your
            agents. Turn this off if your organization needs to avoid AI-generated content (e.g.
            for compliance reasons) — this applies even when the platform has an AI provider
            configured.
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}
