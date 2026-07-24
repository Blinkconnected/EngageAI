import { useState } from 'react'
import {
  Alert,
  Collapse,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useUpdateChannelMutation } from './api'
import { channelTypeLabel, type ChannelConfig, type ChannelConfigUpdateRequest } from './types'

export function ChannelEditDialog({
  channel,
  onClose,
}: {
  channel: ChannelConfig | null
  onClose: () => void
}) {
  if (!channel) return null
  return <ChannelEditDialogFields key={channel.id} channel={channel} onClose={onClose} />
}

function ChannelEditDialogFields({
  channel,
  onClose,
}: {
  channel: ChannelConfig
  onClose: () => void
}) {
  const [displayName, setDisplayName] = useState(channel.display_name)
  const [isActive, setIsActive] = useState(channel.is_active)
  const [rotatingCredentials, setRotatingCredentials] = useState(false)
  const [credentialsJson, setCredentialsJson] = useState('{}')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  const updateMutation = useUpdateChannelMutation()

  function handleSubmit() {
    const payload: ChannelConfigUpdateRequest = { display_name: displayName, is_active: isActive }

    if (rotatingCredentials) {
      try {
        payload.credentials = JSON.parse(credentialsJson || '{}') as Record<string, unknown>
        setJsonError(null)
      } catch {
        setJsonError('Enter valid JSON.')
        return
      }
      if (webhookSecret) payload.webhook_secret = webhookSecret
    }

    updateMutation.mutate({ channelConfigId: channel.id, payload }, { onSuccess: onClose })
  }

  return (
    <FormDialog
      open
      title={`Edit ${channel.display_name}`}
      submitLabel="Save changes"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <Typography variant="body2" color="text.secondary">
        {channelTypeLabel(channel.channel_type)}
      </Typography>
      <TextField
        label="Display name"
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label="Active"
      />

      <FormControlLabel
        control={
          <Switch
            checked={rotatingCredentials}
            onChange={(event) => setRotatingCredentials(event.target.checked)}
          />
        }
        label="Update credentials"
      />
      <Collapse in={rotatingCredentials}>
        <Stack spacing={2}>
          <Alert severity="info">
            Credentials are write-only and never shown once saved — enter new values to replace
            them, or leave this off to keep the current ones.
          </Alert>
          <TextField
            label="Credentials (JSON)"
            value={credentialsJson}
            onChange={(event) => setCredentialsJson(event.target.value)}
            fullWidth
            multiline
            minRows={3}
            error={Boolean(jsonError)}
            helperText={jsonError ?? 'Provider-specific credentials as a JSON object'}
          />
          <TextField
            label="Webhook secret"
            type="password"
            value={webhookSecret}
            onChange={(event) => setWebhookSecret(event.target.value)}
            fullWidth
            helperText="Leave blank to keep the current secret"
          />
        </Stack>
      </Collapse>
    </FormDialog>
  )
}
