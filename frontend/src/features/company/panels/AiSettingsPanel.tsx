import { useState } from 'react'
import {
  Alert,
  Card,
  CardContent,
  Button,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useAiConfigQuery, useUpdateAiConfigMutation } from '../aiConfigApi'
import { useUpdateCompanyMutation } from '../api'
import { AI_CONFIG_PROVIDERS, type AiConfig, type AiConfigProvider } from '../types'
import type { Company } from '../types'

export function AiSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
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
    <Stack spacing={3} sx={{ maxWidth: 520 }}>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            {updateMutation.isError && (
              <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
            )}

            <FormControlLabel
              control={
                <Switch
                  checked={enabled}
                  onChange={(event) => handleChange(event.target.checked)}
                />
              }
              label={t('AiSettingsPanel.enableLabel')}
            />
            <Typography variant="body2" color="text.secondary">
              {t('AiSettingsPanel.description')}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      <AiProviderConfigCard />
      <AutopilotSettingsCard company={company} />
    </Stack>
  )
}

/** Company-wide Autopilot master switch + confidence threshold — the
 * other half of the gate is per-queue (see QueueCreateDialog/
 * QueueEditDialog's own Autopilot toggle); both must be on for a
 * conversation to ever become AI-handled. Shown as a percentage in the
 * UI (0-100), converted to the backend's 0.0-1.0 float on save. */
function AutopilotSettingsCard({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
  const updateMutation = useUpdateCompanyMutation()

  const savedAutopilot = company.settings.ai?.autopilot
  // Defaults mirror the backend's own readers exactly (see
  // domain/company_settings.py): the new-conversation mode defaults ON
  // because it is the behavior that predates modes, the other two OFF.
  const savedOnNewConversation = savedAutopilot?.activate_on_new_conversation ?? true
  const savedOnSla = savedAutopilot?.activate_on_sla ?? false
  const savedOnAgentRequest = savedAutopilot?.activate_on_agent_request ?? false

  const [enabled, setEnabled] = useState(savedAutopilot?.enabled ?? false)
  const [onNewConversation, setOnNewConversation] = useState(savedOnNewConversation)
  const [onSla, setOnSla] = useState(savedOnSla)
  const [onAgentRequest, setOnAgentRequest] = useState(savedOnAgentRequest)
  const [thresholdPercent, setThresholdPercent] = useState(
    Math.round((savedAutopilot?.confidence_threshold ?? 0.7) * 100).toString(),
  )

  const parsedThreshold = Number.parseInt(thresholdPercent, 10)
  const isValid = Number.isFinite(parsedThreshold) && parsedThreshold >= 0 && parsedThreshold <= 100
  const isDirty =
    enabled !== (savedAutopilot?.enabled ?? false) ||
    onNewConversation !== savedOnNewConversation ||
    onSla !== savedOnSla ||
    onAgentRequest !== savedOnAgentRequest ||
    parsedThreshold !== Math.round((savedAutopilot?.confidence_threshold ?? 0.7) * 100)

  function handleSave() {
    if (!isValid) return
    // The whole autopilot object is sent every time: the backend merges
    // settings only one level deep, so a partial autopilot payload
    // replaces the sub-object and would silently drop the modes.
    updateMutation.mutate({
      settings: {
        ai: {
          autopilot: {
            enabled,
            confidence_threshold: parsedThreshold / 100,
            activate_on_new_conversation: onNewConversation,
            activate_on_sla: onSla,
            activate_on_agent_request: onAgentRequest,
          },
        },
      },
    })
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <div>
            <Typography variant="subtitle1" component="p" sx={{ fontWeight: 600 }}>
              {t('AiSettingsPanel.autopilotCardTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('AiSettingsPanel.autopilotCardDescription')}
            </Typography>
          </div>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('AiSettingsPanel.savedAlert')}</Alert>
          )}

          <FormControlLabel
            control={
              <Switch checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            }
            label={t('AiSettingsPanel.autopilotEnableLabel')}
          />

          {enabled && (
            <Stack spacing={0.5} sx={{ pl: 1.5, borderLeft: 2, borderColor: 'divider' }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {t('AiSettingsPanel.activationModesLabel')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                {t('AiSettingsPanel.activationModesDescription')}
              </Typography>
              <FormControlLabel
                control={
                  <Switch
                    checked={onNewConversation}
                    onChange={(event) => setOnNewConversation(event.target.checked)}
                  />
                }
                label={t('AiSettingsPanel.activateOnNewConversationLabel')}
              />
              <FormControlLabel
                control={
                  <Switch checked={onSla} onChange={(event) => setOnSla(event.target.checked)} />
                }
                label={t('AiSettingsPanel.activateOnSlaLabel')}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={onAgentRequest}
                    onChange={(event) => setOnAgentRequest(event.target.checked)}
                  />
                }
                label={t('AiSettingsPanel.activateOnAgentRequestLabel')}
              />
              {!onNewConversation && !onSla && !onAgentRequest && (
                <Alert severity="warning" sx={{ mt: 1 }}>
                  {t('AiSettingsPanel.noActivationModeWarning')}
                </Alert>
              )}
            </Stack>
          )}

          {enabled && (
            <TextField
              label={t('AiSettingsPanel.confidenceThresholdLabel')}
              type="number"
              value={thresholdPercent}
              onChange={(event) => setThresholdPercent(event.target.value)}
              error={!isValid}
              helperText={
                isValid
                  ? t('AiSettingsPanel.confidenceThresholdHelperText')
                  : t('AiSettingsPanel.confidenceThresholdInvalid')
              }
              slotProps={{ htmlInput: { min: 0, max: 100 } }}
              sx={{ maxWidth: 220 }}
            />
          )}

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty || !isValid}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('AiSettingsPanel.autopilotSavingButton')
              : t('AiSettingsPanel.autopilotSaveButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

function AiProviderConfigCard() {
  const { t } = useTranslation('companySettingsExtra')
  const aiConfigQuery = useAiConfigQuery()

  if (aiConfigQuery.isPending) return null
  if (aiConfigQuery.isError) {
    return (
      <Alert severity="error">
        {extractErrorMessage(aiConfigQuery.error, t('AiSettingsPanel.loadErrorFallback'))}
      </Alert>
    )
  }

  // Local form state is only ever initialized from `aiConfig` (never
  // re-synced from a later refetch via an effect — see
  // QueueEditDialog/QueueEditDialogFields for the same "key remounts
  // fresh" split, used here in place of an effect since there's no
  // natural entity id to key on beyond "the config exists now").
  return <AiProviderConfigForm aiConfig={aiConfigQuery.data} />
}

// Every provider except Ollama (self-hosted, typically inside the same
// private network) needs a real API key.
const PROVIDERS_NEEDING_NO_KEY: AiConfigProvider[] = ['ollama']

function AiProviderConfigForm({ aiConfig }: { aiConfig: AiConfig }) {
  const { t } = useTranslation('companySettingsExtra')
  const updateMutation = useUpdateAiConfigMutation()

  const [provider, setProvider] = useState<AiConfigProvider | ''>(aiConfig.provider ?? '')
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [model, setModel] = useState(aiConfig.model ?? '')
  const [baseUrl, setBaseUrl] = useState(aiConfig.base_url ?? '')
  const [deploymentName, setDeploymentName] = useState(aiConfig.deployment_name ?? '')
  const [apiVersion, setApiVersion] = useState(aiConfig.api_version ?? '')

  // A saved key only ever carries forward for the SAME provider it was
  // saved under (company_service.update_ai_config mirrors this) —
  // switching the dropdown to a different vendor must require a fresh
  // key rather than silently reuse (and forward) the old vendor's
  // secret, so this is scoped to the currently-selected provider, not
  // just whatever was loaded.
  const savedApiKeySet = aiConfig.api_key_set && provider === (aiConfig.provider ?? '')
  const isAzure = provider === 'azure_openai'
  const needsApiKey = provider !== '' && !PROVIDERS_NEEDING_NO_KEY.includes(provider)
  const hasUsableKey = savedApiKeySet || apiKeyInput.trim().length > 0
  const isValid =
    (!needsApiKey || hasUsableKey) &&
    (!isAzure || (deploymentName.trim().length > 0 && baseUrl.trim().length > 0))

  const isDirty =
    provider !== (aiConfig.provider ?? '') ||
    model !== (aiConfig.model ?? '') ||
    baseUrl !== (aiConfig.base_url ?? '') ||
    deploymentName !== (aiConfig.deployment_name ?? '') ||
    apiVersion !== (aiConfig.api_version ?? '') ||
    apiKeyInput.trim().length > 0

  function handleSave() {
    updateMutation.mutate(
      {
        provider: provider || null,
        ...(apiKeyInput.trim() ? { api_key: apiKeyInput.trim() } : {}),
        model: model.trim() || null,
        base_url: baseUrl.trim() || null,
        deployment_name: isAzure ? deploymentName.trim() || null : null,
        api_version: isAzure ? apiVersion.trim() || null : null,
      },
      { onSuccess: () => setApiKeyInput('') },
    )
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <div>
            {/* `component="p"` — `subtitle1` maps to `h6` by default,
                which would skip straight from this page's own top-level
                heading with nothing in between (this panel introduces no
                other heading levels), an axe heading-order violation.
                This is a bolded section label, not a real heading. */}
            <Typography variant="subtitle1" component="p" sx={{ fontWeight: 600 }}>
              {t('AiSettingsPanel.providerCardTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('AiSettingsPanel.providerCardDescription')}
            </Typography>
          </div>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('AiSettingsPanel.savedAlert')}</Alert>
          )}

          <TextField
            select
            label={t('AiSettingsPanel.providerLabel')}
            value={provider}
            onChange={(event) => setProvider(event.target.value as AiConfigProvider | '')}
            fullWidth
            // MUI's Select renders blank for an empty-string value unless
            // told otherwise — without this, the "Platform default"
            // MenuItem's own label would never actually be shown. The
            // label must also be forced to `shrink` here: it otherwise
            // only shrinks for a truthy value, so with `displayEmpty` and
            // an empty-string value it would sit un-shrunk, overlapping
            // the displayed "Platform default" text.
            slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
            helperText={t('AiSettingsPanel.providerHelperText')}
          >
            <MenuItem value="">{t('AiSettingsPanel.platformDefaultOption')}</MenuItem>
            {AI_CONFIG_PROVIDERS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>

          {provider && (
            <>
              <Divider />
              {needsApiKey && (
                <TextField
                  label={t('AiSettingsPanel.apiKeyLabel')}
                  type="password"
                  value={apiKeyInput}
                  onChange={(event) => setApiKeyInput(event.target.value)}
                  fullWidth
                  autoComplete="off"
                  error={!isValid}
                  helperText={
                    !isValid
                      ? t('AiSettingsPanel.apiKeyHelperRequired')
                      : savedApiKeySet
                        ? t('AiSettingsPanel.apiKeyHelperAlreadySaved')
                        : t('AiSettingsPanel.apiKeyHelperNeverShown')
                  }
                />
              )}
              <TextField
                label={t('AiSettingsPanel.modelLabel')}
                value={model}
                onChange={(event) => setModel(event.target.value)}
                fullWidth
                helperText={t('AiSettingsPanel.modelHelperText')}
              />
              <TextField
                label={
                  isAzure
                    ? t('AiSettingsPanel.resourceEndpointLabel')
                    : t('AiSettingsPanel.baseUrlLabel')
                }
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                fullWidth
                error={isAzure && !baseUrl.trim()}
                helperText={
                  isAzure
                    ? t('AiSettingsPanel.resourceEndpointHelperText')
                    : provider === 'ollama'
                      ? t('AiSettingsPanel.baseUrlHelperOllama')
                      : t('AiSettingsPanel.baseUrlHelperOptional')
                }
              />
              {isAzure && (
                <>
                  <TextField
                    label={t('AiSettingsPanel.deploymentNameLabel')}
                    value={deploymentName}
                    onChange={(event) => setDeploymentName(event.target.value)}
                    fullWidth
                    required
                    error={!deploymentName.trim()}
                    helperText={t('AiSettingsPanel.deploymentNameHelperText')}
                  />
                  <TextField
                    label={t('AiSettingsPanel.apiVersionLabel')}
                    value={apiVersion}
                    onChange={(event) => setApiVersion(event.target.value)}
                    fullWidth
                    helperText={t('AiSettingsPanel.apiVersionHelperText')}
                  />
                </>
              )}
            </>
          )}

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty || !isValid}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('AiSettingsPanel.providerSavingButton')
              : t('AiSettingsPanel.providerSaveButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
