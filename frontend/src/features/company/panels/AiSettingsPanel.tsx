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
    </Stack>
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

function AiProviderConfigForm({ aiConfig }: { aiConfig: AiConfig }) {
  const { t } = useTranslation('companySettingsExtra')
  const updateMutation = useUpdateAiConfigMutation()

  const [provider, setProvider] = useState<AiConfigProvider | ''>(aiConfig.provider ?? '')
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [model, setModel] = useState(aiConfig.model ?? '')
  const [baseUrl, setBaseUrl] = useState(aiConfig.base_url ?? '')

  const savedApiKeySet = aiConfig.api_key_set
  const needsApiKey = provider === 'openai' || provider === 'claude'
  const hasUsableKey = savedApiKeySet || apiKeyInput.trim().length > 0
  const isValid = !needsApiKey || hasUsableKey

  const isDirty =
    provider !== (aiConfig.provider ?? '') ||
    model !== (aiConfig.model ?? '') ||
    baseUrl !== (aiConfig.base_url ?? '') ||
    apiKeyInput.trim().length > 0

  function handleSave() {
    updateMutation.mutate(
      {
        provider: provider || null,
        ...(apiKeyInput.trim() ? { api_key: apiKeyInput.trim() } : {}),
        model: model.trim() || null,
        base_url: baseUrl.trim() || null,
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
                label={t('AiSettingsPanel.baseUrlLabel')}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                fullWidth
                helperText={
                  provider === 'ollama'
                    ? t('AiSettingsPanel.baseUrlHelperOllama')
                    : t('AiSettingsPanel.baseUrlHelperOptional')
                }
              />
            </>
          )}

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty || !isValid}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('AiSettingsPanel.savingButton')
              : t('AiSettingsPanel.saveButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
