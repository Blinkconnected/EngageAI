import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useResetAgentPasswordMutation } from './api'
import type { Agent } from './types'

export function AgentResetPasswordDialog({
  agent,
  onClose,
}: {
  agent: Agent | null
  onClose: () => void
}) {
  if (!agent) return null
  // Keying on agent.id remounts fresh whenever a different agent is opened.
  return <AgentResetPasswordDialogFields agent={agent} onClose={onClose} key={agent.id} />
}

function AgentResetPasswordDialogFields({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { t } = useTranslation('agents')
  const [newPassword, setNewPassword] = useState('')
  const resetMutation = useResetAgentPasswordMutation()

  function handleClose() {
    resetMutation.reset()
    onClose()
  }

  function handleSubmit() {
    resetMutation.mutate({ agentId: agent.id, newPassword }, { onSuccess: handleClose })
  }

  return (
    <FormDialog
      open
      title={t('AgentResetPasswordDialog.title', { name: agent.full_name })}
      submitLabel={t('AgentResetPasswordDialog.submitLabel')}
      isSubmitting={resetMutation.isPending}
      error={resetMutation.error}
      errorMessage={resetMutation.error ? extractErrorMessage(resetMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('AgentResetPasswordDialog.newPasswordLabel')}
        type="password"
        value={newPassword}
        onChange={(event) => setNewPassword(event.target.value)}
        required
        fullWidth
        autoFocus
        helperText={t('AgentResetPasswordDialog.newPasswordHelperText')}
      />
    </FormDialog>
  )
}
