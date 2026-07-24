import { useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateChannelMutation } from './api'
import { CHANNEL_TYPES, type ChannelConfig } from './types'

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
  const [phoneNumberId, setPhoneNumberId] = useState('')
  const [accessToken, setAccessToken] = useState('')
  const [verifyToken, setVerifyToken] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [credentialsJson, setCredentialsJson] = useState('{}')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [created, setCreated] = useState<ChannelConfig | null>(null)

  const createMutation = useCreateChannelMutation()
  const isWhatsapp = channelType === 'whatsapp'

  function reset() {
    setChannelType('whatsapp')
    setDisplayName('')
    setPhoneNumberId('')
    setAccessToken('')
    setVerifyToken('')
    setWebhookSecret('')
    setCredentialsJson('{}')
    setJsonError(null)
    setCreated(null)
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    let credentials: Record<string, unknown>
    if (isWhatsapp) {
      credentials = {
        phone_number_id: phoneNumberId,
        access_token: accessToken,
        verify_token: verifyToken,
      }
    } else {
      try {
        credentials = JSON.parse(credentialsJson || '{}') as Record<string, unknown>
        setJsonError(null)
      } catch {
        setJsonError('Enter valid JSON.')
        return
      }
    }

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
            <CopyableField label="Webhook URL" value={webhookUrlFor(created.id)} />
            {isWhatsapp && <CopyableField label="Verify token" value={verifyToken} />}
            <Typography variant="body2" color="text.secondary">
              Paste the webhook URL{isWhatsapp ? ' and verify token' : ''} into your provider's
              dashboard to start receiving messages.
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
              onChange={(event) => setChannelType(event.target.value)}
              fullWidth
            >
              {CHANNEL_TYPES.map((type) => (
                <MenuItem key={type.value} value={type.value}>
                  {type.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Display name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              fullWidth
              placeholder={isWhatsapp ? 'e.g. Support WhatsApp' : undefined}
            />

            {isWhatsapp ? (
              <>
                <TextField
                  label="Phone number ID"
                  value={phoneNumberId}
                  onChange={(event) => setPhoneNumberId(event.target.value)}
                  required
                  fullWidth
                  helperText="From Meta's WhatsApp Business App Dashboard"
                />
                <TextField
                  label="Access token"
                  type="password"
                  value={accessToken}
                  onChange={(event) => setAccessToken(event.target.value)}
                  required
                  fullWidth
                />
                <TextField
                  label="Verify token"
                  value={verifyToken}
                  onChange={(event) => setVerifyToken(event.target.value)}
                  required
                  fullWidth
                  helperText="Any string you choose — you'll enter this same value in Meta's dashboard"
                />
              </>
            ) : (
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
            )}

            <TextField
              label="Webhook secret"
              type="password"
              value={webhookSecret}
              onChange={(event) => setWebhookSecret(event.target.value)}
              fullWidth
              helperText="Used to verify inbound webhook signatures"
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
