import { useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateChannelMutation, useTestConnectionEphemeralMutation } from './api'
import { ChannelCredentialFields } from './fields/ChannelCredentialFields'
import { TestConnectionButton } from './TestConnectionButton'
import { CHANNEL_TYPES, hasGuidedSetup, type ChannelConfigCreateResult } from './types'

function webhookUrlFor(channelConfigId: string): string {
  return `${window.location.origin}/api/v1/webhooks/${channelConfigId}`
}

function CopyableField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <TextField
      label={label}
      value={value}
      fullWidth
      slotProps={{
        input: {
          readOnly: true,
          endAdornment: (
            <Tooltip title={copied ? 'Copied!' : 'Copy'}>
              <IconButton
                edge="end"
                aria-label={`Copy ${label}`}
                onClick={() => {
                  void navigator.clipboard.writeText(value)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                }}
              >
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          ),
        },
      }}
    />
  )
}

export function ChannelCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [channelType, setChannelType] = useState('whatsapp')
  const [displayName, setDisplayName] = useState('')
  const [credentials, setCredentials] = useState<Record<string, unknown>>({})
  const [webhookSecret, setWebhookSecret] = useState('')
  const [created, setCreated] = useState<ChannelConfigCreateResult | null>(null)

  const createMutation = useCreateChannelMutation()
  const testConnectionMutation = useTestConnectionEphemeralMutation()
  const isWhatsapp = channelType === 'whatsapp'
  const guided = hasGuidedSetup(channelType)

  function reset() {
    setChannelType('whatsapp')
    setDisplayName('')
    setCredentials({})
    setWebhookSecret('')
    setCreated(null)
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      {
        channel_type: channelType,
        display_name: displayName,
        credentials,
        webhook_secret: webhookSecret || null,
      },
      { onSuccess: setCreated },
    )
  }

  if (created) {
    return (
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
        <DialogTitle>Channel connected</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Alert severity="success">
              {created.display_name} is set up. Finish connecting it on the provider's side using
              the details below.
            </Alert>
            {channelType !== 'web_chat' && (
              <>
                <CopyableField label="Webhook URL" value={webhookUrlFor(created.id)} />
                <CopyableField label="Webhook secret" value={created.webhook_secret} />
              </>
            )}
            {isWhatsapp && created.verify_token && (
              <CopyableField label="Verify token" value={created.verify_token} />
            )}
            <Typography variant="body2" color="text.secondary">
              {channelType === 'web_chat'
                ? "There's nothing further to configure — this channel is live immediately."
                : `Paste the webhook URL, webhook secret${isWhatsapp ? ' and verify token' : ''} into your provider's dashboard to start receiving messages. These values are shown only once — copy them now.`}
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button variant="contained" onClick={handleClose}>
            Done
          </Button>
        </DialogActions>
      </Dialog>
    )
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>Connect a channel</DialogTitle>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          handleSubmit()
        }}
      >
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {createMutation.isError && (
              <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
            )}

            <TextField
              label="Channel type"
              select
              value={channelType}
              onChange={(event) => {
                setChannelType(event.target.value)
                setCredentials({})
              }}
              fullWidth
            >
              {CHANNEL_TYPES.map((type) => (
                <MenuItem key={type.value} value={type.value}>
                  {type.label}
                  {!hasGuidedSetup(type.value) ? ' (manual JSON setup)' : ''}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Display name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              fullWidth
              placeholder={guided ? `e.g. Support ${CHANNEL_TYPES.find((t) => t.value === channelType)?.label}` : undefined}
            />

            <ChannelCredentialFields
              key={channelType}
              channelType={channelType}
              credentials={credentials}
              onChange={setCredentials}
            />

            {channelType !== 'web_chat' && (
              <TextField
                label="Webhook secret"
                type="password"
                value={webhookSecret}
                onChange={(event) => setWebhookSecret(event.target.value)}
                fullWidth
                helperText="Used to verify inbound webhook signatures — leave blank to auto-generate a secure one"
              />
            )}

            <Divider />
            <TestConnectionButton
              key={`${channelType}:${JSON.stringify(credentials)}`}
              onTest={() =>
                testConnectionMutation.mutateAsync({
                  channel_type: channelType,
                  credentials,
                  webhook_secret: webhookSecret || null,
                })
              }
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={handleClose} disabled={createMutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Connecting…' : 'Connect channel'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
