import { useState } from 'react'
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
import {
  useCreateErpConfigMutation,
  useDeleteErpConfigMutation,
  useErpConfigsQuery,
  useTestErpConnectionEphemeralMutation,
  useTestErpConnectionMutation,
} from './api'

function ConnectErpForm() {
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
            Connect your ERPNext instance to view customer invoices, orders, and more from their
            profile.
          </Typography>
          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}
          <TextField
            label="ERPNext site URL"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            required
            fullWidth
            placeholder="https://your-site.erpnext.com"
          />
          <TextField
            label="API key"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            required
            fullWidth
          />
          <TextField
            label="API secret"
            type="password"
            value={apiSecret}
            onChange={(event) => setApiSecret(event.target.value)}
            required
            fullWidth
          />
          <TextField
            label="Webhook secret"
            type="password"
            value={webhookSecret}
            onChange={(event) => setWebhookSecret(event.target.value)}
            fullWidth
            helperText="Shared secret ERPNext sends in the X-Webhook-Secret header"
          />

          {testConnectionMutation.data && (
            <Alert severity={testConnectionMutation.data.healthy ? 'success' : 'error'}>
              {testConnectionMutation.data.healthy
                ? 'Connection successful.'
                : (testConnectionMutation.data.detail ?? 'Connection failed.')}
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
            {testConnectionMutation.isPending ? 'Testing…' : 'Test Connection'}
          </Button>

          <Button
            type="submit"
            variant="contained"
            disabled={createMutation.isPending}
            sx={{ alignSelf: 'flex-start' }}
          >
            {createMutation.isPending ? 'Connecting…' : 'Connect ERPNext'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

/** The connect-form-or-connected-status body shared by the standalone
 * `/erp-configs` page and Company Settings' conditional ERP tab (only
 * shown once the company enables ERP — see
 * `docs/architecture/company-onboarding.md`). Extracted so neither one
 * duplicates the CRUD/test-connection logic. */
export function ErpConnectionPanel() {
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const configsQuery = useErpConfigsQuery({ page: 1, page_size: 1 })
  const deleteMutation = useDeleteErpConfigMutation()
  const testConnectionMutation = useTestErpConnectionMutation()
  const config = configsQuery.data?.items[0]

  if (configsQuery.isPending) return <LoadingState label="Loading ERPNext connection…" />
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
                label={config.is_active ? 'Active' : 'Inactive'}
                size="small"
                color={config.is_active ? 'success' : 'default'}
                sx={{ mt: 1 }}
              />
            </Box>
            {testConnectionMutation.data && (
              <Alert severity={testConnectionMutation.data.healthy ? 'success' : 'error'}>
                {testConnectionMutation.data.healthy
                  ? 'Connection successful.'
                  : (testConnectionMutation.data.detail ?? 'Connection failed.')}
              </Alert>
            )}
            <Stack direction="row" spacing={2}>
              <Button
                variant="outlined"
                disabled={testConnectionMutation.isPending}
                onClick={() => testConnectionMutation.mutate(config.id)}
              >
                {testConnectionMutation.isPending ? 'Testing…' : 'Test Connection'}
              </Button>
              <Button
                color="error"
                variant="outlined"
                onClick={() => setConfirmingDelete(true)}
              >
                Disconnect
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmingDelete}
        title="Disconnect ERPNext"
        description="Customer profiles will stop showing ERPNext records until you reconnect."
        confirmLabel="Yes, disconnect"
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
