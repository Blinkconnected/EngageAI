import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAdvanceSessionMutation, useConnectMutation, useStartSessionMutation } from './api'
import {
  ChecklistStep,
  FormStep,
  OAuthStep,
  ResourcePickerStep,
  SummaryStep,
} from './StepRenderers'
import { useConnectCopy, useOptionalCopy } from './copy'
import type { ConnectorManifest, WizardSession } from './types'

/**
 * The connection wizard.
 *
 * **This component contains no channel names and no hardcoded steps.** It
 * asks the server what the flow is, renders each step by its `kind`, and
 * sends the answer back. Connecting WhatsApp and connecting Telegram run this
 * same code down to the branch; the difference is entirely in what the server
 * described.
 *
 * The progress indicator comes from `session.steps`, so a connector with four
 * steps shows four and one with five shows five — a customer who has
 * connected one channel recognises the second.
 *
 * State is deliberately thin. The server owns the flow and every call returns
 * the whole session, so there is no local state machine to drift out of step
 * with it. What lives here is only what the customer has typed but not yet
 * submitted.
 */
export function ConnectionWizard({
  channelType,
  templateKey,
  manifest,
  onClose,
  onConnected,
}: {
  channelType?: string
  templateKey?: string
  manifest?: ConnectorManifest
  onClose: () => void
  onConnected: (count: number) => void
}) {
  const { t } = useTranslation('connectSdk')
  const copy = useConnectCopy()
  const optional = useOptionalCopy()

  const start = useStartSessionMutation()
  const advance = useAdvanceSessionMutation()
  const connect = useConnectMutation()

  const [session, setSession] = useState<WizardSession | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string[]>([])
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    start.mutate(
      { channelType, templateKey },
      {
        onSuccess: setSession,
        onError: (err) => setError(extractErrorMessage(err, t('wizard.couldNotStart'))),
      },
    )
    // Started once, for the channel this wizard was opened on. A dependency
    // on the mutation object would restart the flow on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelType, templateKey])

  const current = session?.current_step
  const activeIndex = useMemo(
    () => session?.steps.findIndex((step) => step.id === current?.id) ?? 0,
    [session, current],
  )

  const missingRequired = useMemo(() => {
    if (current?.kind !== 'form') return false
    return (session?.fields ?? []).some(
      (field) => field.required && !String(values[field.name] ?? '').trim(),
    )
  }, [current, session, values])

  const blocked = (session?.checks ?? []).some((check) => check.blocks)

  function submit() {
    if (!session) return
    setError(null)
    const payload: Record<string, unknown> =
      current?.kind === 'form'
        ? { ...values, display_name: displayName }
        : current?.kind === 'resource_picker'
          ? {
              selected: Object.fromEntries(session.channel_types.map((type) => [type, selected])),
            }
          : {}

    advance.mutate(
      { sessionId: session.session_id, payload },
      {
        onSuccess: setSession,
        onError: (err) => setError(extractErrorMessage(err, t('wizard.couldNotContinue'))),
      },
    )
  }

  function finish() {
    if (!session) return
    setError(null)
    connect.mutate(session.session_id, {
      onSuccess: (result) => onConnected(result.channels.length),
      onError: (err) => setError(extractErrorMessage(err, t('wizard.couldNotConnect'))),
    })
  }

  const busy = start.isPending || advance.isPending || connect.isPending

  return (
    <Dialog open fullWidth maxWidth="sm" onClose={busy ? undefined : onClose}>
      <DialogTitle>
        {manifest ? copy(manifest.name_key) : t('wizard.title')}
        {manifest && (
          <Typography variant="body2" color="text.secondary">
            {optional(manifest.description_key)}
          </Typography>
        )}
      </DialogTitle>

      <DialogContent>
        {session && (
          <Stepper activeStep={activeIndex} sx={{ mb: 3, mt: 1 }} alternativeLabel>
            {session.steps.map((step) => (
              <Step key={step.id} completed={step.state === 'complete'}>
                <StepLabel>{copy(step.title_key)}</StepLabel>
              </Step>
            ))}
          </Stepper>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Box sx={{ minHeight: 180 }}>
          {/* The switch that keeps a channel name out of this component. Six
              cases cover every connector that exists and every one planned;
              a seventh would mean something genuinely new about connecting to
              things, which is worth adding deliberately rather than
              discovering inside a screen full of per-channel branches. */}
          {current?.kind === 'form' && (
            <FormStep
              fields={session?.fields ?? []}
              values={values}
              onChange={(name, value) => setValues((previous) => ({ ...previous, [name]: value }))}
              disabled={busy}
            />
          )}
          {current?.kind === 'oauth_redirect' && (
            <OAuthStep
              authorizeUrl={session?.authorize_url ?? null}
              permissions={manifest?.required_permissions ?? []}
            />
          )}
          {current?.kind === 'resource_picker' && (
            <ResourcePickerStep
              resources={session?.resources ?? []}
              selected={selected}
              multiple={manifest?.required_resources.some((r) => r.multiple) ?? false}
              emptyKey={manifest?.required_resources[0]?.empty_key}
              onToggle={(id) =>
                setSelected((previous) => {
                  const multiple = manifest?.required_resources.some((r) => r.multiple) ?? false
                  if (previous.includes(id)) return previous.filter((x) => x !== id)
                  return multiple ? [...previous, id] : [id]
                })
              }
            />
          )}
          {current?.kind === 'checklist' && (
            <ChecklistStep checks={session?.checks ?? []} running={advance.isPending} />
          )}
          {current?.kind === 'summary' && (
            <SummaryStep
              channelTypes={session?.channel_types ?? []}
              displayName={displayName}
              onDisplayNameChange={setDisplayName}
              nameLabel={t('wizard.summary.nameLabel')}
            />
          )}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t('wizard.cancel')}
        </Button>
        {current?.kind === 'summary' ? (
          <Button
            variant="contained"
            onClick={finish}
            // Refused here *and* on the server. The button is a courtesy; the
            // server's refusal is the guarantee.
            disabled={busy || blocked}
          >
            {t('wizard.connect')}
          </Button>
        ) : (
          <Button
            variant="contained"
            onClick={submit}
            disabled={busy || missingRequired || (current?.kind === 'checklist' && blocked)}
          >
            {t('wizard.continue')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
