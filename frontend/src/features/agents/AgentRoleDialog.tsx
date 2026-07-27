import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle, MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAgentRoleQuery, useRolesQuery, useUpdateAgentRoleMutation } from '../roles/api'
import type { Role } from '../roles/types'
import type { Agent } from './types'

export function AgentRoleDialog({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const { t } = useTranslation('agents')
  const agentRoleQuery = useAgentRoleQuery(agent?.id ?? null)
  const rolesQuery = useRolesQuery()

  if (!agent) return null

  if (agentRoleQuery.isError || rolesQuery.isError) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>{t('AgentRoleDialog.changeRoleTitle')}</DialogTitle>
        <DialogContent>
          <ErrorState error={agentRoleQuery.error ?? rolesQuery.error} />
        </DialogContent>
      </Dialog>
    )
  }

  if (!agentRoleQuery.data || !rolesQuery.data) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>{t('AgentRoleDialog.changeRoleTitle')}</DialogTitle>
        <DialogContent>
          <LoadingState label={t('AgentRoleDialog.loadingLabel')} />
        </DialogContent>
      </Dialog>
    )
  }

  // Keying on agent.id remounts fresh whenever a different agent is
  // opened, so the role picker simply initializes from the now-loaded
  // current role (see QueueEditDialog/QueueEditDialogFields for the same
  // pattern).
  return (
    <AgentRoleDialogFields
      agent={agent}
      currentRoleId={agentRoleQuery.data.role_id}
      roles={rolesQuery.data}
      onClose={onClose}
      key={agent.id}
    />
  )
}

function AgentRoleDialogFields({
  agent,
  currentRoleId,
  roles,
  onClose,
}: {
  agent: Agent
  currentRoleId: string
  roles: Role[]
  onClose: () => void
}) {
  const { t } = useTranslation('agents')
  const [roleId, setRoleId] = useState(currentRoleId)
  const updateMutation = useUpdateAgentRoleMutation()

  function handleSubmit() {
    updateMutation.mutate({ agentId: agent.id, roleId }, { onSuccess: onClose })
  }

  return (
    <FormDialog
      open
      title={t('AgentRoleDialog.title', { name: agent.full_name })}
      submitLabel={t('AgentRoleDialog.submitLabel')}
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        select
        label={t('AgentRoleDialog.roleLabel')}
        value={roleId}
        onChange={(event) => setRoleId(event.target.value)}
        fullWidth
        autoFocus
      >
        {roles.map((role) => (
          <MenuItem key={role.id} value={role.id}>
            {role.name}
          </MenuItem>
        ))}
      </TextField>
    </FormDialog>
  )
}
