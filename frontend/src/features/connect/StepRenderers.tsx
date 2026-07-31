import { useState } from 'react'
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckCircleIcon from '@mui/icons-material/CheckCircleOutlined'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useTranslation } from 'react-i18next'
import { useConnectCopy } from './copy'
import type { ConnectCheck, ConnectField, DiscoveredResource } from './types'

/**
 * Six renderers, one per `StepKind`, and **nothing here knows what a channel
 * is**.
 *
 * That is the rule the whole connector SDK exists to make possible. A screen
 * that asks *which channel is this?* has to be changed for every channel
 * added after it; one that asks *what kind of step is this?* does not. When
 * Slack or RCS ships, none of these components change — the server describes
 * the step and these draw it.
 *
 * Everything a customer reads is a translation key resolved here. The server
 * sends keys precisely so this file can put them through `t()`, which is what
 * makes the same flow Arabic.
 */

// --- form ------------------------------------------------------------

/** Fields the server described, rendered without knowing what they mean.
 *
 * `copyable` is the quiet centrepiece. It appears exactly when the customer
 * has to do something outside Blink Engage — send `/newbot` to BotFather,
 * paste a URL into someone's dashboard — which is the moment a setup flow
 * usually loses people. Putting the exact text next to the field with a copy
 * button is what replaces "see the provider's documentation".
 */
export function FormStep({
  fields,
  values,
  onChange,
  disabled,
}: {
  fields: ConnectField[]
  values: Record<string, string>
  onChange: (name: string, value: string) => void
  disabled?: boolean
}) {
  const copy = useConnectCopy()
  const { t } = useTranslation('connectSdk')
  const [copied, setCopied] = useState<string | null>(null)

  if (fields.length === 0) {
    // Web Chat asks for nothing. An empty step with an explanation reads as
    // finished; an empty step with nothing on it reads as broken.
    return (
      <Alert severity="info" icon={<InfoOutlinedIcon />}>
        {t('wizard.form.nothingToEnter')}
      </Alert>
    )
  }

  return (
    <Stack spacing={2.5}>
      {fields.map((field) => {
        const label = copy(field.label_key)
        const help = copy(field.help_key)
        if (field.kind === 'boolean') {
          return (
            <FormControlLabel
              key={field.name}
              control={
                <Checkbox
                  checked={values[field.name] === 'true'}
                  onChange={(event) =>
                    onChange(field.name, String(event.target.checked))
                  }
                  disabled={disabled}
                />
              }
              label={
                <Stack>
                  <Typography variant="body2">{label}</Typography>
                  {help && (
                    <Typography variant="caption" color="text.secondary">
                      {help}
                    </Typography>
                  )}
                </Stack>
              }
            />
          )
        }
        return (
          <Box key={field.name}>
            <TextField
              fullWidth
              select={field.kind === 'select'}
              type={field.kind === 'secret' ? 'password' : 'text'}
              label={label}
              value={values[field.name] ?? ''}
              onChange={(event) => onChange(field.name, event.target.value)}
              required={field.required}
              disabled={disabled}
              helperText={help || undefined}
              placeholder={field.placeholder ?? undefined}
              slotProps={
                field.kind === 'number'
                  ? { htmlInput: { inputMode: 'numeric' } }
                  : undefined
              }
            >
              {field.kind === 'select' &&
                field.options.map(([value, labelKey]) => (
                  <MenuItem key={value} value={value}>
                    {copy(labelKey)}
                  </MenuItem>
                ))}
            </TextField>
            {field.copyable && (
              <Stack
                direction="row"
                spacing={1}
                sx={{ mt: 1, alignItems: 'center' }}
              >
                <Typography variant="caption" color="text.secondary">
                  {t('wizard.form.copyThis')}
                </Typography>
                <Chip
                  size="small"
                  label={field.copyable}
                  sx={{ fontFamily: 'monospace' }}
                />
                <Tooltip
                  title={
                    copied === field.name
                      ? t('wizard.form.copied')
                      : t('wizard.form.copy')
                  }
                >
                  <IconButton
                    size="small"
                    onClick={() => {
                      void navigator.clipboard?.writeText(field.copyable ?? '')
                      setCopied(field.name)
                    }}
                    aria-label={t('wizard.form.copy')}
                  >
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            )}
          </Box>
        )
      })}
    </Stack>
  )
}

// --- oauth_redirect --------------------------------------------------

export function OAuthStep({
  authorizeUrl,
  permissions,
}: {
  authorizeUrl: string | null
  permissions: string[]
}) {
  const { t } = useTranslation('connectSdk')

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {t('wizard.oauth.explanation')}
      </Typography>
      {permissions.length > 0 && (
        <Box>
          {/* Shown before the customer leaves, not after. Somebody about to
              approve a permission list deserves to have read it here, where
              they can still ask a colleague. */}
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {t('wizard.oauth.willAskFor')}
          </Typography>
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
            {permissions.map((permission) => (
              <Chip key={permission} size="small" label={permission} />
            ))}
          </Stack>
        </Box>
      )}
      <Button
        variant="contained"
        size="large"
        endIcon={<OpenInNewIcon />}
        href={authorizeUrl ?? undefined}
        disabled={!authorizeUrl}
        sx={{ alignSelf: 'flex-start' }}
      >
        {t('wizard.oauth.continue')}
      </Button>
    </Stack>
  )
}

// --- resource_picker -------------------------------------------------

/** What discovery found, grouped as the connector asked.
 *
 * Unavailable resources are shown and disabled rather than filtered out. A
 * customer who cannot find their Page assumes the product is broken; one who
 * sees it greyed with a reason knows exactly what to fix.
 */
export function ResourcePickerStep({
  resources,
  selected,
  onToggle,
  multiple,
  emptyKey,
}: {
  resources: DiscoveredResource[]
  selected: string[]
  onToggle: (id: string) => void
  multiple: boolean
  emptyKey?: string | null
}) {
  const copy = useConnectCopy()
  const { t } = useTranslation('connectSdk')

  if (resources.length === 0) {
    return (
      <Alert severity="warning">
        {copy(emptyKey) || t('wizard.picker.nothingFound')}
      </Alert>
    )
  }

  const groups = new Map<string, DiscoveredResource[]>()
  for (const resource of resources) {
    const key = resource.group_key ?? ''
    groups.set(key, [...(groups.get(key) ?? []), resource])
  }

  return (
    <Stack spacing={2}>
      {[...groups.entries()].map(([groupKey, group]) => (
        <Box key={groupKey}>
          {groupKey && (
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
              {copy(groupKey)}
            </Typography>
          )}
          <List dense disablePadding>
            {group.map((resource) => {
              const blocked = Boolean(resource.unavailable_reason)
              return (
                <ListItemButton
                  key={resource.id}
                  selected={selected.includes(resource.id)}
                  disabled={blocked}
                  onClick={() => onToggle(resource.id)}
                  sx={{ borderRadius: 1 }}
                >
                  <ListItemText
                    primary={resource.label}
                    secondary={
                      blocked
                        ? copy(`resource.${resource.unavailable_reason}`)
                        : Object.entries(resource.detail)
                            .filter(([, value]) => value)
                            .map(([key, value]) => `${copy(`detail.${key}`)}: ${value}`)
                            .join(' · ')
                    }
                  />
                  {selected.includes(resource.id) && (
                    <CheckCircleIcon fontSize="small" color="success" />
                  )}
                </ListItemButton>
              )
            })}
          </List>
        </Box>
      ))}
      {multiple && (
        <Typography variant="caption" color="text.secondary">
          {t('wizard.picker.chooseSeveral')}
        </Typography>
      )}
    </Stack>
  )
}

/** Which key describes a finding.
 *
 * A connector reports a code from the closed set (`invalid_token`) and often
 * passes the *specific* condition as `params.check` — a full key it already
 * owns, like `connect.sms.check.numberUnverified`. Preferring that gives the
 * customer the specific sentence; falling back to the generic code means a
 * connector that passes nothing still reads correctly.
 */
function checkCopyKey(check: ConnectCheck): string {
  return check.params.check || `check.${check.code}`
}

// --- checklist -------------------------------------------------------

/** What the connector found, and what to do about it.
 *
 * The distinction the customer needs is *blocking or not*, and the server
 * already decided it — centrally, so one channel cannot stop somebody for
 * what another waves through. This renders that decision and does not
 * second-guess it.
 */
export function ChecklistStep({
  checks,
  running,
  onRepair,
}: {
  checks: ConnectCheck[]
  running?: boolean
  onRepair?: (actionId: string) => void
}) {
  const copy = useConnectCopy()
  const { t } = useTranslation('connectSdk')

  if (running) {
    return (
      <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
        <CircularProgress size={18} />
        <Typography variant="body2" color="text.secondary">
          {t('wizard.checklist.running')}
        </Typography>
      </Stack>
    )
  }

  if (checks.length === 0) {
    return <Alert severity="success">{t('wizard.checklist.nothingWrong')}</Alert>
  }

  return (
    <Stack spacing={1.5}>
      {checks.map((check, index) => (
        <Alert
          key={`${check.code}-${index}`}
          severity={check.blocks ? 'error' : check.code === 'ok' ? 'success' : 'warning'}
          icon={check.blocks ? <ErrorOutlineIcon /> : undefined}
          action={
            check.repair_action && onRepair ? (
              <Button
                size="small"
                onClick={() => onRepair(check.repair_action as string)}
              >
                {t('wizard.checklist.fixIt')}
              </Button>
            ) : undefined
          }
        >
          <AlertTitle sx={{ mb: check.instructions_key ? 0.5 : 0 }}>
            {copy(checkCopyKey(check), check.params)}
          </AlertTitle>
          {check.instructions_key && (
            <Typography variant="body2">{copy(check.instructions_key, check.params)}</Typography>
          )}
        </Alert>
      ))}
    </Stack>
  )
}

// --- summary ---------------------------------------------------------

export function SummaryStep({
  channelTypes,
  displayName,
  onDisplayNameChange,
  nameLabel,
}: {
  channelTypes: string[]
  displayName: string
  onDisplayNameChange: (value: string) => void
  nameLabel: string
}) {
  const { t } = useTranslation('connectSdk')

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {t('wizard.summary.aboutToConnect', { count: channelTypes.length })}
      </Typography>
      <TextField
        fullWidth
        label={nameLabel}
        value={displayName}
        onChange={(event) => onDisplayNameChange(event.target.value)}
        helperText={t('wizard.summary.nameHelp')}
      />
    </Stack>
  )
}
