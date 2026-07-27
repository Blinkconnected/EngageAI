import { useState } from 'react'
import { Divider, FormControlLabel, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { EscalationRulesEditor } from './EscalationRulesEditor'
import { useUpdateSlaPolicyMutation } from './api'
import type { EscalationRule, SlaPolicy } from './types'

function parseTargetMinutes(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function SlaPolicyEditDialog({
  policy,
  onClose,
}: {
  policy: SlaPolicy | null
  onClose: () => void
}) {
  if (!policy) return null
  // Keying on policy.id remounts fresh whenever a different policy is
  // opened (see QueueEditDialog/QueueEditDialogFields for the same
  // pattern).
  return <SlaPolicyEditDialogFields policy={policy} onClose={onClose} key={policy.id} />
}

function SlaPolicyEditDialogFields({
  policy,
  onClose,
}: {
  policy: SlaPolicy
  onClose: () => void
}) {
  const [name, setName] = useState(policy.name)
  const [description, setDescription] = useState(policy.description ?? '')
  const [firstResponseTarget, setFirstResponseTarget] = useState(
    policy.first_response_target_minutes?.toString() ?? '',
  )
  const [resolutionTarget, setResolutionTarget] = useState(
    policy.resolution_target_minutes?.toString() ?? '',
  )
  const [warningThreshold, setWarningThreshold] = useState(
    policy.warning_threshold_percent.toString(),
  )
  const [businessHoursAware, setBusinessHoursAware] = useState(policy.business_hours_aware)
  const [isActive, setIsActive] = useState(policy.is_active)
  const [escalationRules, setEscalationRules] = useState<EscalationRule[]>(
    policy.escalation_rules,
  )

  const updateMutation = useUpdateSlaPolicyMutation()

  function handleSubmit() {
    updateMutation.mutate(
      {
        policyId: policy.id,
        payload: {
          name,
          description: description || null,
          first_response_target_minutes: parseTargetMinutes(firstResponseTarget),
          resolution_target_minutes: parseTargetMinutes(resolutionTarget),
          warning_threshold_percent: Number.parseInt(warningThreshold, 10) || 80,
          business_hours_aware: businessHoursAware,
          escalation_rules: escalationRules,
          is_active: isActive,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={`Edit ${policy.name}`}
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
        label="First response target (minutes)"
        type="number"
        value={firstResponseTarget}
        onChange={(event) => setFirstResponseTarget(event.target.value)}
        fullWidth
        helperText="Leave blank for no first-response SLA."
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label="Resolution target (minutes)"
        type="number"
        value={resolutionTarget}
        onChange={(event) => setResolutionTarget(event.target.value)}
        fullWidth
        helperText="Leave blank for no resolution SLA."
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label="Warning threshold (%)"
        type="number"
        value={warningThreshold}
        onChange={(event) => setWarningThreshold(event.target.value)}
        fullWidth
        helperText="Warn once this percentage of a target has elapsed, before it actually breaches."
        slotProps={{ htmlInput: { min: 1, max: 100 } }}
      />
      <FormControlLabel
        control={
          <Switch
            checked={businessHoursAware}
            onChange={(event) => setBusinessHoursAware(event.target.checked)}
          />
        }
        label="Business-hours aware"
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label="Active"
      />
      <Divider />
      <EscalationRulesEditor rules={escalationRules} onChange={setEscalationRules} />
    </FormDialog>
  )
}
