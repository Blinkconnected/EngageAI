import { useState } from 'react'
import { Divider, FormControlLabel, Switch, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { EscalationRulesEditor } from './EscalationRulesEditor'
import { useCreateSlaPolicyMutation } from './api'
import type { EscalationRule } from './types'

function parseTargetMinutes(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function SlaPolicyCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('sla')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [firstResponseTarget, setFirstResponseTarget] = useState('')
  const [resolutionTarget, setResolutionTarget] = useState('')
  const [warningThreshold, setWarningThreshold] = useState('80')
  const [businessHoursAware, setBusinessHoursAware] = useState(true)
  const [escalationRules, setEscalationRules] = useState<EscalationRule[]>([])

  const createMutation = useCreateSlaPolicyMutation()

  function reset() {
    setName('')
    setDescription('')
    setFirstResponseTarget('')
    setResolutionTarget('')
    setWarningThreshold('80')
    setBusinessHoursAware(true)
    setEscalationRules([])
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
        first_response_target_minutes: parseTargetMinutes(firstResponseTarget),
        resolution_target_minutes: parseTargetMinutes(resolutionTarget),
        warning_threshold_percent: Number.parseInt(warningThreshold, 10) || 80,
        business_hours_aware: businessHoursAware,
        escalation_rules: escalationRules,
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title={t('SlaPolicyCreateDialog.dialogTitle')}
      submitLabel={t('SlaPolicyCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('SlaPolicyCreateDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('SlaPolicyCreateDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      <TextField
        label={t('SlaPolicyCreateDialog.firstResponseTargetLabel')}
        type="number"
        value={firstResponseTarget}
        onChange={(event) => setFirstResponseTarget(event.target.value)}
        fullWidth
        helperText={t('SlaPolicyCreateDialog.firstResponseTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label={t('SlaPolicyCreateDialog.resolutionTargetLabel')}
        type="number"
        value={resolutionTarget}
        onChange={(event) => setResolutionTarget(event.target.value)}
        fullWidth
        helperText={t('SlaPolicyCreateDialog.resolutionTargetHelperText')}
        slotProps={{ htmlInput: { min: 1 } }}
      />
      <TextField
        label={t('SlaPolicyCreateDialog.warningThresholdLabel')}
        type="number"
        value={warningThreshold}
        onChange={(event) => setWarningThreshold(event.target.value)}
        fullWidth
        helperText={t('SlaPolicyCreateDialog.warningThresholdHelperText')}
        slotProps={{ htmlInput: { min: 1, max: 100 } }}
      />
      <FormControlLabel
        control={
          <Switch
            checked={businessHoursAware}
            onChange={(event) => setBusinessHoursAware(event.target.checked)}
          />
        }
        label={t('SlaPolicyCreateDialog.businessHoursAwareLabel')}
      />
      <Divider />
      <EscalationRulesEditor rules={escalationRules} onChange={setEscalationRules} />
    </FormDialog>
  )
}
