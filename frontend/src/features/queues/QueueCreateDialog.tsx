import { useState } from 'react'
import { FormControlLabel, MenuItem, Switch, TextField, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation('queues')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [assignmentStrategy, setAssignmentStrategy] = useState<QueueAssignmentStrategy>('manual')
  const [firstResponseTarget, setFirstResponseTarget] = useState('')
  const [resolutionTarget, setResolutionTarget] = useState('')
  const [slaPolicyId, setSlaPolicyId] = useState('')
  const [autopilotEnabled, setAutopilotEnabled] = useState(false)

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
    setAutopilotEnabled(false)
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
        autopilot_enabled: autopilotEnabled,
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title={t('QueueCreateDialog.title')}
      submitLabel={t('QueueCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('QueueCreateDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('QueueCreateDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      <TextField
        select
        label={t('QueueCreateDialog.departmentLabel')}
        value={departmentId}
        disabled={departmentsQuery.isPending}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        helperText={t('QueueCreateDialog.departmentHelperText')}
      >
        <MenuItem value="">{t('QueueCreateDialog.noDepartmentOption')}</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label={t('QueueCreateDialog.assignmentStrategyLabel')}
        value={assignmentStrategy}
        onChange={(event) => setAssignmentStrategy(event.target.value as QueueAssignmentStrategy)}
        fullWidth
        helperText={t('QueueCreateDialog.assignmentStrategyHelperText')}
      >
        {QUEUE_ASSIGNMENT_STRATEGIES.map((strategy) => (
          <MenuItem key={strategy.value} value={strategy.value}>
            {strategy.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label={t('QueueCreateDialog.slaPolicyLabel')}
        value={slaPolicyId}
        disabled={slaPoliciesQuery.isPending}
        onChange={(event) => setSlaPolicyId(event.target.value)}
        fullWidth
        slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
        helperText={t('QueueCreateDialog.slaPolicyHelperText')}
      >
        <MenuItem value="">{t('QueueCreateDialog.noSlaPolicyOption')}</MenuItem>
        {slaPoliciesQuery.data?.map((policy) => (
          <MenuItem key={policy.id} value={policy.id}>
            {policy.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label={t('QueueCreateDialog.firstResponseTargetLabel')}
        type="number"
        value={firstResponseTarget}
        onChange={(event) => setFirstResponseTarget(event.target.value)}
        fullWidth
        helperText={t('QueueCreateDialog.firstResponseTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label={t('QueueCreateDialog.resolutionTargetLabel')}
        type="number"
        value={resolutionTarget}
        onChange={(event) => setResolutionTarget(event.target.value)}
        fullWidth
        helperText={t('QueueCreateDialog.resolutionTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <FormControlLabel
        control={
          <Switch
            checked={autopilotEnabled}
            onChange={(event) => setAutopilotEnabled(event.target.checked)}
          />
        }
        label={t('QueueCreateDialog.autopilotLabel')}
      />
      <Typography variant="caption" color="text.secondary">
        {t('QueueCreateDialog.autopilotHelperText')}
      </Typography>
    </FormDialog>
  )
}
