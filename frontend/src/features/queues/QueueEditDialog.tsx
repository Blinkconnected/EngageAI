import { useState } from 'react'
import { Alert, FormControlLabel, Link, MenuItem, Switch, TextField, Typography } from '@mui/material'
import { Trans, useTranslation } from 'react-i18next'
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

export function QueueEditDialog({ queue, onClose }: { queue: Queue | null; onClose: () => void }) {
  if (!queue) return null
  // Keying on queue.id remounts fresh whenever a different queue is
  // opened, so fields simply initialize from props (see
  // DepartmentEditDialog for the same pattern).
  return <QueueEditDialogFields queue={queue} onClose={onClose} key={queue.id} />
}

function QueueEditDialogFields({ queue, onClose }: { queue: Queue; onClose: () => void }) {
  const { t } = useTranslation('queues')
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
  const [autopilotEnabled, setAutopilotEnabled] = useState(queue.autopilot_enabled)

  const departmentsQuery = useAllDepartmentsQuery()
  const slaPoliciesQuery = useSlaPoliciesQuery()
  const updateMutation = useUpdateQueueMutation()

  // When a service owns this queue's SLA, these three fields are read-only
  // and the API refuses a change to them with a 409.
  const slaOwner = queue.sla_owned_by_service

  function handleSubmit() {
    updateMutation.mutate(
      {
        queueId: queue.id,
        payload: {
          name,
          description: description || null,
          department_id: departmentId || null,
          assignment_strategy: assignmentStrategy,
          // Omitted entirely when a service owns them. Sending the unchanged
          // values would also be accepted — the API refuses a *change*, not
          // the field's presence — but not sending what this screen cannot
          // edit is the honest request, and it keeps working if somebody
          // edits the service in another tab while this dialog is open.
          ...(slaOwner
            ? {}
            : {
                first_response_target_minutes: parseTargetMinutes(firstResponseTarget),
                resolution_target_minutes: parseTargetMinutes(resolutionTarget),
                sla_policy_id: slaPolicyId || null,
              }),
          is_active: isActive,
          autopilot_enabled: autopilotEnabled,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={t('QueueEditDialog.title', { name: queue.name })}
      submitLabel={t('QueueEditDialog.submitLabel')}
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label={t('QueueEditDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('QueueEditDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      <TextField
        select
        label={t('QueueEditDialog.departmentLabel')}
        value={departmentId}
        disabled={departmentsQuery.isPending}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        helperText={t('QueueEditDialog.departmentHelperText')}
      >
        <MenuItem value="">{t('QueueEditDialog.noDepartmentOption')}</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label={t('QueueEditDialog.assignmentStrategyLabel')}
        value={assignmentStrategy}
        onChange={(event) => setAssignmentStrategy(event.target.value as QueueAssignmentStrategy)}
        fullWidth
      >
        {QUEUE_ASSIGNMENT_STRATEGIES.map((strategy) => (
          <MenuItem key={strategy.value} value={strategy.value}>
            {strategy.label}
          </MenuItem>
        ))}
      </TextField>
      {slaOwner ? (
        // Said before the disabled fields, not after. Somebody who reads the
        // explanation first understands why they are greyed out; somebody who
        // meets the grey first has already started wondering whether the page
        // is broken.
        <Alert severity="info" icon={false}>
          <Trans
            i18nKey="QueueEditDialog.slaOwnedByService"
            ns="queues"
            values={{ service: slaOwner.service_name }}
            components={{
              serviceLink: <Link href={`/services/${slaOwner.service_id}`} />,
            }}
          />
        </Alert>
      ) : null}
      <TextField
        select
        label={t('QueueEditDialog.slaPolicyLabel')}
        value={slaPolicyId}
        disabled={slaPoliciesQuery.isPending || Boolean(slaOwner)}
        onChange={(event) => setSlaPolicyId(event.target.value)}
        fullWidth
        slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
        helperText={t('QueueEditDialog.slaPolicyHelperText')}
      >
        <MenuItem value="">{t('QueueEditDialog.noSlaPolicyOption')}</MenuItem>
        {slaPoliciesQuery.data?.map((policy) => (
          <MenuItem key={policy.id} value={policy.id}>
            {policy.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label={t('QueueEditDialog.firstResponseTargetLabel')}
        type="number"
        value={firstResponseTarget}
        onChange={(event) => setFirstResponseTarget(event.target.value)}
        disabled={Boolean(slaOwner)}
        fullWidth
        helperText={t('QueueEditDialog.firstResponseTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label={t('QueueEditDialog.resolutionTargetLabel')}
        type="number"
        value={resolutionTarget}
        onChange={(event) => setResolutionTarget(event.target.value)}
        disabled={Boolean(slaOwner)}
        fullWidth
        helperText={t('QueueEditDialog.resolutionTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label={t('QueueEditDialog.activeLabel')}
      />
      <FormControlLabel
        control={
          <Switch
            checked={autopilotEnabled}
            onChange={(event) => setAutopilotEnabled(event.target.checked)}
          />
        }
        label={t('QueueEditDialog.autopilotLabel')}
      />
      <Typography variant="caption" color="text.secondary">
        {t('QueueEditDialog.autopilotHelperText')}
      </Typography>
    </FormDialog>
  )
}
