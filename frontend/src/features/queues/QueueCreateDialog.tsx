import { useState } from 'react'
import { MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useSlaPoliciesQuery } from '../sla/api'
import { useCreateQueueMutation } from './api'
import { QUEUE_ASSIGNMENT_STRATEGIES, type QueueAssignmentStrategy } from './types'

/** Parses a text field's value into the nullable-positive-int shape
 * QueueCreateRequest/QueueUpdateRequest expect for SLA targets — an empty
 * field means "no target", not zero. */
function parseTargetMinutes(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function QueueCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [assignmentStrategy, setAssignmentStrategy] = useState<QueueAssignmentStrategy>('manual')
  const [firstResponseTarget, setFirstResponseTarget] = useState('')
  const [resolutionTarget, setResolutionTarget] = useState('')
  const [slaPolicyId, setSlaPolicyId] = useState('')

  const departmentsQuery = useAllDepartmentsQuery()
  const slaPoliciesQuery = useSlaPoliciesQuery()
  const createMutation = useCreateQueueMutation()

  function reset() {
    setName('')
    setDescription('')
    setDepartmentId('')
    setAssignmentStrategy('manual')
    setFirstResponseTarget('')
    setResolutionTarget('')
    setSlaPolicyId('')
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      {
        name,
        description: description || null,
        department_id: departmentId || null,
        assignment_strategy: assignmentStrategy,
        first_response_target_minutes: parseTargetMinutes(firstResponseTarget),
        resolution_target_minutes: parseTargetMinutes(resolutionTarget),
        sla_policy_id: slaPolicyId || null,
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title="New queue"
      submitLabel="Create queue"
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label="Name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      <TextField
        select
        label="Department"
        value={departmentId}
        disabled={departmentsQuery.isPending}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        helperText="Organizational label only — doesn't restrict who can pick up work here."
      >
        <MenuItem value="">No department</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label="Assignment strategy"
        value={assignmentStrategy}
        onChange={(event) =>
          setAssignmentStrategy(event.target.value as QueueAssignmentStrategy)
        }
        fullWidth
        helperText="Manual: conversations wait for an agent to pick them up. Round robin/Least load assign automatically."
      >
        {QUEUE_ASSIGNMENT_STRATEGIES.map((strategy) => (
          <MenuItem key={strategy.value} value={strategy.value}>
            {strategy.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label="SLA policy"
        value={slaPolicyId}
        disabled={slaPoliciesQuery.isPending}
        onChange={(event) => setSlaPolicyId(event.target.value)}
        fullWidth
        slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
        helperText="Optional — overrides the targets below with a reusable policy (business hours, warning threshold, escalation). See Roles & SLA → SLA Builder."
      >
        <MenuItem value="">None (use targets below)</MenuItem>
        {slaPoliciesQuery.data?.map((policy) => (
          <MenuItem key={policy.id} value={policy.id}>
            {policy.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="First response target (minutes)"
        type="number"
        value={firstResponseTarget}
        onChange={(event) => setFirstResponseTarget(event.target.value)}
        fullWidth
        helperText="Leave blank for no first-response SLA on this queue. Ignored while an SLA policy above is set."
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label="Resolution target (minutes)"
        type="number"
        value={resolutionTarget}
        onChange={(event) => setResolutionTarget(event.target.value)}
        fullWidth
        helperText="Leave blank for no resolution SLA on this queue. Ignored while an SLA policy above is set."
        slotProps={{ htmlInput: { min: 1 } }}
      />
    </FormDialog>
  )
}
