import { useState } from 'react'
import {
  Alert,
  Collapse,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useTestConnectionEphemeralMutation, useTestConnectionMutation, useUpdateChannelMutation } from './api'
import { ChannelCredentialFields } from './fields/ChannelCredentialFields'
import { ChannelHealthBadge } from './ChannelHealthBadge'
import { TestConnectionButton } from './TestConnectionButton'
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
  const [credentials, setCredentials] = useState<Record<string, unknown>>({})
  const [webhookSecret, setWebhookSecret] = useState('')

  const updateMutation = useUpdateChannelMutation()
  const testConnectionMutation = useTestConnectionMutation()
  const testConnectionEphemeralMutation = useTestConnectionEphemeralMutation()

  function handleSubmit() {
    const payload: ChannelConfigUpdateRequest = { display_name: displayName, is_active: isActive }
    if (rotatingCredentials) {
      payload.credentials = credentials
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
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          {channelTypeLabel(channel.channel_type)}
        </Typography>
        <ChannelHealthBadge channel={channel} />
      </Stack>
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

      {channel.channel_type !== 'web_chat' && (
        <FormControlLabel
          control={
            <Switch
              checked={rotatingCredentials}
              onChange={(event) => setRotatingCredentials(event.target.checked)}
            />
          }
          label="Update credentials (reconnect)"
        />
      )}
      <Collapse in={rotatingCredentials}>
        {/* Conditionally MOUNTED, not just visually collapsed: MUI's
            Collapse only animates height, it doesn't unmount children —
            an empty `required` field inside would still block native
            HTML5 form validation on "Save changes" even while hidden,
            silently preventing unrelated changes (e.g. just renaming)
            from ever submitting. */}
        {rotatingCredentials && (
          <Stack spacing={2}>
            <Alert severity="info">
              Credentials are write-only and never shown once saved — enter new values to replace
              them, then Test Connection to confirm they work before saving.
            </Alert>
            <ChannelCredentialFields
              channelType={channel.channel_type}
              credentials={credentials}
              onChange={setCredentials}
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
        )}
      </Collapse>

      <Divider />
      <TestConnectionButton
        key={rotatingCredentials ? `rotating:${JSON.stringify(credentials)}` : 'saved'}
        onTest={() =>
          rotatingCredentials
            ? testConnectionEphemeralMutation.mutateAsync({
                channel_type: channel.channel_type,
                credentials,
                webhook_secret: webhookSecret || null,
              })
            : testConnectionMutation.mutateAsync(channel.id)
        }
      />
    </FormDialog>
  )
}
