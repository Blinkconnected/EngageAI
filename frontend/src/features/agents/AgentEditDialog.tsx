import { useState } from 'react'
import { MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useUpdateAgentMutation } from './api'
import type { Agent, AgentStatus } from './types'

const STATUS_OPTIONS: AgentStatus[] = ['online', 'away', 'offline']

export function AgentEditDialog({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  if (!agent) return null
  // Keying on agent.id remounts this dialog fresh whenever a different agent
  // is opened, so its fields simply initialize from props — no effect
  // needed to "resync" local state with an external prop.
  return <AgentEditDialogFields key={agent.id} agent={agent} onClose={onClose} />
}

function AgentEditDialogFields({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const [title, setTitle] = useState(agent.title ?? '')
  const [departmentId, setDepartmentId] = useState(agent.department_id ?? '')
  const [status, setStatus] = useState<AgentStatus>(agent.status)

  const departmentsQuery = useAllDepartmentsQuery()
  const updateMutation = useUpdateAgentMutation()

  function handleSubmit() {
    updateMutation.mutate(
      {
        agentId: agent.id,
        payload: { title: title || null, department_id: departmentId || null, status },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={`Edit ${agent.full_name}`}
      submitLabel="Save changes"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label="Title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        fullWidth
        autoFocus
      />
      <TextField
        label="Department"
        select
        value={departmentId}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        disabled={departmentsQuery.isPending}
      >
        <MenuItem value="">None</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Status"
        select
        value={status}
        onChange={(event) => setStatus(event.target.value as AgentStatus)}
        fullWidth
      >
        {STATUS_OPTIONS.map((option) => (
          <MenuItem key={option} value={option}>
            {option}
          </MenuItem>
        ))}
      </TextField>
    </FormDialog>
  )
}
