import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { ErpConfigEditDialog } from './ErpConfigEditDialog'
import {
  useCreateErpConfigMutation,
  useDeleteErpConfigMutation,
  useErpConfigsQuery,
  useTestErpConnectionEphemeralMutation,
  useTestErpConnectionMutation,
} from './api'

function ConnectErpForm() {
  const { t } = useTranslation('erp')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')
  const createMutation = useCreateErpConfigMutation()
  const testConnectionMutation = useTestErpConnectionEphemeralMutation()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createMutation.mutate({
      base_url: baseUrl,
      credentials: { api_key: apiKey, api_secret: apiSecret },
      webhook_secret: webhookSecret || null,
    })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="body2" color="text.secondary">
            {t('ErpConnectionPanel.connectFormDescription')}
          </Typography>
          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}
          <TextField
            label={t('ErpConnectionPanel.siteUrlLabel')}
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            required
            fullWidth
            placeholder={t('ErpConnectionPanel.siteUrlPlaceholder')}
          />
          <TextField
            label={t('ErpConnectionPanel.apiKeyLabel')}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            required
            fullWidth
          />
          <TextField
            label={t('ErpConnectionPanel.apiSecretLabel')}
            type="password"
            value={apiSecret}
            onChange={(event) => setApiSecret(event.target.value)}
            required
            fullWidth
          />
          <TextField
            label={t('ErpConnectionPanel.webhookSecretLabel')}
            type="password"
            value={webhookSecret}
            onChange={(event) => setWebhookSecret(event.target.value)}
            fullWidth
            helperText={t('ErpConnectionPanel.webhookSecretHelperText')}
          />

          {testConnectionMutation.data && (
            <Alert severity={testConnectionMutation.data.healthy ? 'success' : 'error'}>
              {testConnectionMutation.data.healthy
                ? t('ErpConnectionPanel.connectionSuccessAlert')
                : (testConnectionMutation.data.detail ??
                  t('ErpConnectionPanel.connectionFailedAlert'))}
            </Alert>
          )}
          <Button
            variant="outlined"
            disabled={!baseUrl || !apiKey || !apiSecret || testConnectionMutation.isPending}
            onClick={() =>
              testConnectionMutation.mutate({
                base_url: baseUrl,
                credentials: { api_key: apiKey, api_secret: apiSecret },
              })
            }
            sx={{ alignSelf: 'flex-start' }}
          >
            {testConnectionMutation.isPending
              ? t('ErpConnectionPanel.testingButton')
              : t('ErpConnectionPanel.testConnectionButton')}
          </Button>

          <Button
            type="submit"
            variant="contained"
            disabled={createMutation.isPending}
            sx={{ alignSelf: 'flex-start' }}
          >
            {createMutation.isPending
              ? t('ErpConnectionPanel.connectingButton')
              : t('ErpConnectionPanel.connectButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

/** The connect-form-or-connected-status body shared by the standalone
 * `/erp-configs` page and Settings' conditional ERP tab (only
 * shown once the company enables ERP — see
 * `docs/architecture/company-onboarding.md`). Extracted so neither one
 * duplicates the CRUD/test-connection logic. */
export function ErpConnectionPanel() {
  const { t } = useTranslation('erp')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const configsQuery = useErpConfigsQuery({ page: 1, page_size: 1 })
  const deleteMutation = useDeleteErpConfigMutation()
  const testConnectionMutation = useTestErpConnectionMutation()
  const config = configsQuery.data?.items[0]

  if (configsQuery.isPending) return <LoadingState label={t('ErpConnectionPanel.loadingLabel')} />
  if (configsQuery.isError) {
    return <ErrorState error={configsQuery.error} onRetry={() => configsQuery.refetch()} />
  }

  if (!config) return <ConnectErpForm />

  return (
    <>
      <Card variant="outlined" sx={{ maxWidth: 520 }}>
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" color="text.secondary">
                {config.base_url}
              </Typography>
              <Chip
                label={
                  config.is_active
                    ? t('ErpConnectionPanel.activeChip')
                    : t('ErpConnectionPanel.inactiveChip')
                }
                size="small"
                color={config.is_active ? 'success' : 'default'}
                sx={{ mt: 1 }}
              />
            </Box>
            {testConnectionMutation.data && (
              <Alert severity={testConnectionMutation.data.healthy ? 'success' : 'error'}>
                {testConnectionMutation.data.healthy
                  ? t('ErpConnectionPanel.connectionSuccessAlert')
                  : (testConnectionMutation.data.detail ??
                    t('ErpConnectionPanel.connectionFailedAlert'))}
              </Alert>
            )}
            <Stack direction="row" spacing={2}>
              <Button
                variant="outlined"
                disabled={testConnectionMutation.isPending}
                onClick={() => testConnectionMutation.mutate(config.id)}
              >
                {testConnectionMutation.isPending
                  ? t('ErpConnectionPanel.testingButton')
                  : t('ErpConnectionPanel.testConnectionButton')}
              </Button>
              <Button variant="outlined" onClick={() => setEditing(true)}>
                {t('ErpConnectionPanel.editButton')}
              </Button>
              <Button color="error" variant="outlined" onClick={() => setConfirmingDelete(true)}>
                {t('ErpConnectionPanel.disconnectButton')}
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <ErpConfigEditDialog config={editing ? config : null} onClose={() => setEditing(false)} />

      <ConfirmDialog
        open={confirmingDelete}
        title={t('ErpConnectionPanel.disconnectDialogTitle')}
        description={t('ErpConnectionPanel.disconnectDialogDescription')}
        confirmLabel={t('ErpConnectionPanel.disconnectConfirmLabel')}
        confirmColor="error"
        isConfirming={deleteMutation.isPending}
        onConfirm={() => {
          deleteMutation.mutate(config.id, { onSuccess: () => setConfirmingDelete(false) })
        }}
        onClose={() => setConfirmingDelete(false)}
      />
    </>
  )
}
