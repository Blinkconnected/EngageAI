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

export function ChannelCreateDialog({
  open,
  onClose,
  initialChannelType = 'whatsapp',
}: {
  open: boolean
  onClose: () => void
  /** Pre-selects a channel type — e.g. the Company Onboarding Wizard's
   * "Connect WhatsApp"/"Connect Web Chat" shortcut buttons. */
  initialChannelType?: string
}) {
  const [channelType, setChannelType] = useState(initialChannelType)
  const [displayName, setDisplayName] = useState('')
  const [credentials, setCredentials] = useState<Record<string, unknown>>({})
  const [webhookSecret, setWebhookSecret] = useState('')
  const [created, setCreated] = useState<ChannelConfigCreateResult | null>(null)

  const createMutation = useCreateChannelMutation()
  const testConnectionMutation = useTestConnectionEphemeralMutation()
  const isWhatsapp = channelType === 'whatsapp'
  const guided = hasGuidedSetup(channelType)

  function reset() {
    setChannelType(initialChannelType)
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
    // Telegram's webhook is registered automatically server-side (see
    // ChannelConfigService._register_webhook) — unlike WhatsApp/
    // Messenger/Instagram, Telegram has no dashboard to paste a webhook
    // URL into, so showing "paste this into your provider's dashboard"
    // for it would be actively wrong, not just unnecessary.
    const isTelegram = channelType === 'telegram'
    const needsManualDashboardStep = channelType !== 'web_chat' && !isTelegram

    return (
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
        <DialogTitle>Channel connected</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Alert severity="success">
              {created.display_name} is set up.{' '}
              {needsManualDashboardStep
                ? "Finish connecting it on the provider's side using the details below."
                : "It's live — no further setup needed."}
            </Alert>
            {needsManualDashboardStep && (
              <>
                <CopyableField label="Webhook URL" value={webhookUrlFor(created.id)} />
                <CopyableField label="Webhook secret" value={created.webhook_secret} />
              </>
            )}
            {isWhatsapp && created.verify_token && (
              <CopyableField label="Verify token" value={created.verify_token} />
            )}
            <Typography variant="body2" color="text.secondary">
              {needsManualDashboardStep
                ? `Paste the webhook URL, webhook secret${isWhatsapp ? ' and verify token' : ''} into your provider's dashboard to start receiving messages. These values are shown only once — copy them now.`
                : isTelegram
                  ? 'Telegram has no dashboard for this — BlinkEngage already registered the webhook with your bot automatically. Send it a message to try it out.'
                  : "There's nothing further to configure — this channel is live immediately."}
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
