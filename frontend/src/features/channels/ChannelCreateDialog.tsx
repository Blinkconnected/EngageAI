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
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateChannelMutation, useTestConnectionEphemeralMutation } from './api'
import { ChannelCredentialFields } from './fields/ChannelCredentialFields'
import { TestConnectionButton } from './TestConnectionButton'
import { CHANNEL_TYPES, hasGuidedSetup, type ChannelConfigCreateResult } from './types'

function webhookUrlFor(channelConfigId: string): string {
  return `${window.location.origin}/api/v1/webhooks/${channelConfigId}`
}

function CopyableField({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation('channelsCore')
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
            <Tooltip
              title={
                copied
                  ? t('ChannelCreateDialog.copiedTooltip')
                  : t('ChannelCreateDialog.copyTooltip')
              }
            >
              <IconButton
                edge="end"
                aria-label={t('ChannelCreateDialog.copyFieldAriaLabel', { label })}
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
  const { t } = useTranslation('channelsCore')
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
        <DialogTitle>{t('ChannelCreateDialog.channelConnectedTitle')}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Alert severity="success">
              {needsManualDashboardStep
                ? t('ChannelCreateDialog.connectedAlertManual', { name: created.display_name })
                : t('ChannelCreateDialog.connectedAlertReady', { name: created.display_name })}
            </Alert>
            {needsManualDashboardStep && (
              <>
                <CopyableField
                  label={t('ChannelCreateDialog.webhookUrlLabel')}
                  value={webhookUrlFor(created.id)}
                />
                <CopyableField
                  label={t('ChannelCreateDialog.webhookSecretLabel')}
                  value={created.webhook_secret}
                />
              </>
            )}
            {isWhatsapp && created.verify_token && (
              <CopyableField
                label={t('ChannelCreateDialog.verifyTokenLabel')}
                value={created.verify_token}
              />
            )}
            <Typography variant="body2" color="text.secondary">
              {needsManualDashboardStep
                ? isWhatsapp
                  ? t('ChannelCreateDialog.pasteInstructionsWithVerifyToken')
                  : t('ChannelCreateDialog.pasteInstructionsBase')
                : isTelegram
                  ? t('ChannelCreateDialog.telegramAutoRegistered')
                  : t('ChannelCreateDialog.noFurtherSetupNeeded')}
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button variant="contained" onClick={handleClose}>
            {t('ChannelCreateDialog.doneButton')}
          </Button>
        </DialogActions>
      </Dialog>
    )
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('ChannelCreateDialog.dialogTitle')}</DialogTitle>
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
              label={t('ChannelCreateDialog.channelTypeFieldLabel')}
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
                  {!hasGuidedSetup(type.value)
                    ? t('ChannelCreateDialog.manualJsonSetupSuffix')
                    : ''}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label={t('ChannelCreateDialog.displayNameLabel')}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
              fullWidth
              placeholder={
                guided
                  ? t('ChannelCreateDialog.displayNamePlaceholder', {
                      label: CHANNEL_TYPES.find((ct) => ct.value === channelType)?.label,
                    })
                  : undefined
              }
            />

            <ChannelCredentialFields
              key={channelType}
              channelType={channelType}
              credentials={credentials}
              onChange={setCredentials}
            />

            {channelType !== 'web_chat' && (
              <TextField
                label={t('ChannelCreateDialog.webhookSecretLabel')}
                type="password"
                value={webhookSecret}
                onChange={(event) => setWebhookSecret(event.target.value)}
                fullWidth
                helperText={t('ChannelCreateDialog.webhookSecretHelperText')}
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
            {t('ChannelCreateDialog.cancelButton')}
          </Button>
          <Button type="submit" variant="contained" disabled={createMutation.isPending}>
            {createMutation.isPending
              ? t('ChannelCreateDialog.connectingButton')
              : t('ChannelCreateDialog.connectChannelButton')}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
