import { useState } from 'react'
import { FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useSlaPoliciesQuery } from '../sla/api'
import { useUpdateQueueMutation } from './api'
import { QUEUE_ASSIGNMENT_STRATEGIES, type Queue, type QueueAssignmentStrategy } from './types'

function parseTargetMinutes(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function QueueEditDialog({
  queue,
  onClose,
}: {
  queue: Queue | null
  onClose: () => void
}) {
  if (!queue) return null
  // Keying on queue.id remounts fresh whenever a different queue is
  // opened, so fields simply initialize from props (see
  // DepartmentEditDialog for the same pattern).
  return <QueueEditDialogFields queue={queue} onClose={onClose} key={queue.id} />
}

function QueueEditDialogFields({ queue, onClose }: { queue: Queue; onClose: () => void }) {
  const [name, setName] = useState(queue.name)
  const [description, setDescription] = useState(queue.description ?? '')
  const [departmentId, setDepartmentId] = useState(queue.department_id ?? '')
  const [assignmentStrategy, setAssignmentStrategy] = useState<QueueAssignmentStrategy>(
    queue.assignment_strategy,
  )
  const [firstResponseTarget, setFirstResponseTarget] = useState(
    queue.first_response_target_minutes?.toString() ?? '',
  )
  const [resolutionTarget, setResolutionTarget] = useState(
    queue.resolution_target_minutes?.toString() ?? '',
  )
  const [isActive, setIsActive] = useState(queue.is_active)
  const [slaPolicyId, setSlaPolicyId] = useState(queue.sla_policy_id ?? '')

  const departmentsQuery = useAllDepartmentsQuery()
  const slaPoliciesQuery = useSlaPoliciesQuery()
  const updateMutation = useUpdateQueueMutation()

  function handleSubmit() {
    updateMutation.mutate(
      {
        queueId: queue.id,
        payload: {
          name,
          description: description || null,
          department_id: departmentId || null,
          assignment_strategy: assignmentStrategy,
          first_response_target_minutes: parseTargetMinutes(firstResponseTarget),
          resolution_target_minutes: parseTargetMinutes(resolutionTarget),
          is_active: isActive,
          sla_policy_id: slaPolicyId || null,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={`Edit ${queue.name}`}
      submitLabel="Save changes"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
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
        helperText="Optional — overrides the targets below with a reusable policy (business hours, warning threshold, escalation). See SLA Builder."
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
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label="Active"
      />
    </FormDialog>
  )
}
