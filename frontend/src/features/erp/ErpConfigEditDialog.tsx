import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Collapse, FormControlLabel, Stack, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import {
  useTestErpConnectionEphemeralMutation,
  useTestErpConnectionMutation,
  useUpdateErpConfigMutation,
} from './api'
import type { ErpConfig, ErpConfigUpdateRequest } from './types'

export function ErpConfigEditDialog({
  config,
  onClose,
}: {
  config: ErpConfig | null
  onClose: () => void
}) {
  if (!config) return null
  return <ErpConfigEditDialogFields key={config.id} config={config} onClose={onClose} />
}

function ErpConfigEditDialogFields({
  config,
  onClose,
}: {
  config: ErpConfig
  onClose: () => void
}) {
  const { t } = useTranslation('erp')
  const [baseUrl, setBaseUrl] = useState(config.base_url)
  const [isActive, setIsActive] = useState(config.is_active)
  const [rotatingCredentials, setRotatingCredentials] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')

  const updateMutation = useUpdateErpConfigMutation()
  const testConnectionMutation = useTestErpConnectionMutation()
  const testConnectionEphemeralMutation = useTestErpConnectionEphemeralMutation()

  function handleSubmit() {
    const payload: ErpConfigUpdateRequest = { base_url: baseUrl, is_active: isActive }
    if (rotatingCredentials) {
      payload.credentials = { api_key: apiKey, api_secret: apiSecret }
      if (webhookSecret) payload.webhook_secret = webhookSecret
    }
    updateMutation.mutate({ erpConfigId: config.id, payload }, { onSuccess: onClose })
  }

  const testResult = rotatingCredentials
    ? testConnectionEphemeralMutation.data
    : testConnectionMutation.data
  const testPending = rotatingCredentials
    ? testConnectionEphemeralMutation.isPending
    : testConnectionMutation.isPending

  function handleTestConnection() {
    if (rotatingCredentials) {
      testConnectionEphemeralMutation.mutate({
        base_url: baseUrl,
        credentials: { api_key: apiKey, api_secret: apiSecret },
      })
    } else {
      testConnectionMutation.mutate(config.id)
    }
  }

  return (
    <FormDialog
      open
      title={t('ErpConfigEditDialog.dialogTitle')}
      submitLabel={t('ErpConfigEditDialog.submitLabel')}
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label={t('ErpConfigEditDialog.siteUrlLabel')}
        value={baseUrl}
        onChange={(event) => setBaseUrl(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label={t('ErpConfigEditDialog.activeLabel')}
      />

      <FormControlLabel
        control={
          <Switch
            checked={rotatingCredentials}
            onChange={(event) => setRotatingCredentials(event.target.checked)}
          />
        }
        label={t('ErpConfigEditDialog.updateCredentialsLabel')}
      />
      <Collapse in={rotatingCredentials}>
        {/* Conditionally MOUNTED, not just visually collapsed — see
            ChannelEditDialog's identical comment: an empty `required`
            field here would otherwise block "Save changes" even while
            hidden. */}
        {rotatingCredentials && (
          <Stack spacing={2}>
            <Alert severity="info">{t('ErpConfigEditDialog.credentialsInfoAlert')}</Alert>
            <TextField
              label={t('ErpConfigEditDialog.apiKeyLabel')}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label={t('ErpConfigEditDialog.apiSecretLabel')}
              type="password"
              value={apiSecret}
              onChange={(event) => setApiSecret(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label={t('ErpConfigEditDialog.webhookSecretLabel')}
              type="password"
              value={webhookSecret}
              onChange={(event) => setWebhookSecret(event.target.value)}
              fullWidth
              helperText={t('ErpConfigEditDialog.webhookSecretHelperText')}
            />
          </Stack>
        )}
      </Collapse>

      {testResult && (
        <Alert severity={testResult.healthy ? 'success' : 'error'}>
          {testResult.healthy
            ? t('ErpConfigEditDialog.connectionSuccessAlert')
            : (testResult.detail ?? t('ErpConfigEditDialog.connectionFailedAlert'))}
        </Alert>
      )}
      <Button
        variant="outlined"
        disabled={(rotatingCredentials && (!apiKey || !apiSecret)) || !baseUrl || testPending}
        onClick={handleTestConnection}
        sx={{ alignSelf: 'flex-start' }}
      >
        {testPending
          ? t('ErpConfigEditDialog.testingButton')
          : t('ErpConfigEditDialog.testConnectionButton')}
      </Button>
    </FormDialog>
  )
}
