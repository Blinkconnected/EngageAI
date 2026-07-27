import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { extractErrorMessage } from '../../shared/api/errors'
import { useConversationsQuery } from '../conversations/api'
import { useAllAgentsQuery, useRemoveAgentMutation } from './api'
import type { Agent } from './types'

type Step = 'choose' | 'confirm-transfer' | 'confirm-permanent-1' | 'confirm-permanent-2'

/** Deleting an agent needs an explicit disposition for their currently
 * assigned conversations first — either transfer them all to another
 * agent, or permanently delete the agent together with them. Permanent
 * deletion is gated behind two separate confirmation steps (an explicit
 * consequences warning, then a type-the-agent's-name confirmation) since
 * it can't be undone the way a transfer can (transfer again). See
 * docs/architecture/administration.md. */
export function AgentRemovalDialog({
  agent,
  onClose,
}: {
  agent: Agent | null
  onClose: () => void
}) {
  if (!agent) return null
  return <AgentRemovalDialogFields agent={agent} onClose={onClose} key={agent.id} />
}

function AgentRemovalDialogFields({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { t } = useTranslation('agents')
  const [step, setStep] = useState<Step>('choose')
  const [mode, setMode] = useState<'transfer' | 'permanent'>('transfer')
  const [targetAgent, setTargetAgent] = useState<Agent | null>(null)
  const [confirmationText, setConfirmationText] = useState('')

  const agentsQuery = useAllAgentsQuery()
  const otherAgents = (agentsQuery.data ?? []).filter((candidate) => candidate.id !== agent.id)
  const conversationsQuery = useConversationsQuery({
    page: 1,
    page_size: 1,
    assigned_agent_id: agent.id,
  })
  const conversationCount = conversationsQuery.data?.total ?? 0
  const removeMutation = useRemoveAgentMutation()

  function handleClose() {
    removeMutation.reset()
    onClose()
  }

  function handleRemove() {
    removeMutation.mutate(
      {
        agentId: agent.id,
        payload:
          mode === 'transfer'
            ? { mode: 'transfer' as const, transfer_to_agent_id: targetAgent?.id }
            : { mode: 'permanent' as const },
      },
      { onSuccess: handleClose },
    )
  }

  const canContinueFromChoose = mode === 'transfer' ? Boolean(targetAgent) : true
  const permanentConfirmationMatches = confirmationText.trim() === agent.full_name

  return (
    <Dialog open onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('AgentRemovalDialog.title', { name: agent.full_name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {removeMutation.isError && (
            <Alert severity="error">
              {extractErrorMessage(removeMutation.error, t('AgentRemovalDialog.errorFallback'))}
            </Alert>
          )}

          {step === 'choose' && (
            <>
              <Typography variant="body2" color="text.secondary">
                {conversationCount > 0
                  ? t('AgentRemovalDialog.conversationsWarning', { count: conversationCount })
                  : t('AgentRemovalDialog.noConversations')}
              </Typography>
              <ToggleButtonGroup
                value={mode}
                exclusive
                fullWidth
                onChange={(_event, value: 'transfer' | 'permanent' | null) => {
                  if (value) setMode(value)
                }}
              >
                <ToggleButton value="transfer">
                  {t('AgentRemovalDialog.transferToggle')}
                </ToggleButton>
                <ToggleButton value="permanent">
                  {t('AgentRemovalDialog.permanentToggle')}
                </ToggleButton>
              </ToggleButtonGroup>

              {mode === 'transfer' ? (
                <Autocomplete
                  options={otherAgents}
                  getOptionLabel={(candidate) => candidate.full_name}
                  value={targetAgent}
                  onChange={(_event, value) => setTargetAgent(value)}
                  loading={agentsQuery.isPending}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label={t('AgentRemovalDialog.searchAgentsLabel')}
                      autoFocus
                    />
                  )}
                />
              ) : (
                <Alert severity="warning">{t('AgentRemovalDialog.permanentWarning')}</Alert>
              )}
            </>
          )}

          {step === 'confirm-transfer' && (
            <Typography>
              {t('AgentRemovalDialog.confirmTransferMessage', {
                agentName: agent.full_name,
                targetName: targetAgent?.full_name ?? '',
              })}
            </Typography>
          )}

          {step === 'confirm-permanent-1' && (
            <Stack spacing={1}>
              <Alert severity="error">
                {t('AgentRemovalDialog.confirmPermanentMessage', {
                  agentName: agent.full_name,
                  count: conversationCount,
                })}
              </Alert>
              <Typography variant="body2" color="text.secondary">
                {t('AgentRemovalDialog.irreversibleNote')}
              </Typography>
            </Stack>
          )}

          {step === 'confirm-permanent-2' && (
            <Stack spacing={2}>
              <Typography>
                {t('AgentRemovalDialog.typeToConfirmMessage', { name: agent.full_name })}
              </Typography>
              <TextField
                label={t('AgentRemovalDialog.typeToConfirmLabel')}
                value={confirmationText}
                onChange={(event) => setConfirmationText(event.target.value)}
                fullWidth
                autoFocus
                placeholder={agent.full_name}
              />
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={removeMutation.isPending}>
          {t('AgentRemovalDialog.cancelButton')}
        </Button>

        {step === 'choose' && (
          <Button
            variant="contained"
            disabled={!canContinueFromChoose}
            onClick={() =>
              setStep(mode === 'transfer' ? 'confirm-transfer' : 'confirm-permanent-1')
            }
          >
            {t('AgentRemovalDialog.continueButton')}
          </Button>
        )}

        {step === 'confirm-transfer' && (
          <>
            <Button onClick={() => setStep('choose')} disabled={removeMutation.isPending}>
              {t('AgentRemovalDialog.backButton')}
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={handleRemove}
              disabled={removeMutation.isPending}
            >
              {removeMutation.isPending
                ? t('AgentRemovalDialog.removingButton')
                : t('AgentRemovalDialog.confirmTransferButton')}
            </Button>
          </>
        )}

        {step === 'confirm-permanent-1' && (
          <>
            <Button onClick={() => setStep('choose')} disabled={removeMutation.isPending}>
              {t('AgentRemovalDialog.backButton')}
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={() => setStep('confirm-permanent-2')}
            >
              {t('AgentRemovalDialog.continueButton')}
            </Button>
          </>
        )}

        {step === 'confirm-permanent-2' && (
          <>
            <Button
              onClick={() => setStep('confirm-permanent-1')}
              disabled={removeMutation.isPending}
            >
              {t('AgentRemovalDialog.backButton')}
            </Button>
            <Button
              variant="contained"
              color="error"
              disabled={!permanentConfirmationMatches || removeMutation.isPending}
              onClick={handleRemove}
            >
              {removeMutation.isPending
                ? t('AgentRemovalDialog.removingButton')
                : t('AgentRemovalDialog.confirmPermanentButton')}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  )
}
