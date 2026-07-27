import { useState } from 'react'
import { FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { CHANNEL_TYPES } from '../channels/types'
import { useAllQueuesQuery, useUpdateRoutingRuleMutation } from './api'
import type { RoutingRule } from './types'

export function RoutingRuleEditDialog({
  rule,
  onClose,
}: {
  rule: RoutingRule | null
  onClose: () => void
}) {
  if (!rule) return null
  // Keying on rule.id remounts fresh whenever a different rule is opened.
  return <RoutingRuleEditDialogFields rule={rule} onClose={onClose} key={rule.id} />
}

function RoutingRuleEditDialogFields({
  rule,
  onClose,
}: {
  rule: RoutingRule
  onClose: () => void
}) {
  const { t } = useTranslation('queues')
  const [priority, setPriority] = useState(rule.priority.toString())
  const [targetQueueId, setTargetQueueId] = useState(rule.target_queue_id)
  const [channelType, setChannelType] = useState(rule.conditions.channel_type ?? '')
  const [bodyContains, setBodyContains] = useState(rule.conditions.body_contains ?? '')
  const [isActive, setIsActive] = useState(rule.is_active)

  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateRoutingRuleMutation()

  function handleSubmit() {
    updateMutation.mutate(
      {
        ruleId: rule.id,
        payload: {
          priority: Number.parseInt(priority, 10) || 0,
          target_queue_id: targetQueueId,
          conditions: {
            ...(channelType ? { channel_type: channelType } : {}),
            ...(bodyContains ? { body_contains: bodyContains } : {}),
          },
          is_active: isActive,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={t('RoutingRuleEditDialog.title')}
      submitLabel={t('RoutingRuleEditDialog.submitLabel')}
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label={t('RoutingRuleEditDialog.priorityLabel')}
        type="number"
        value={priority}
        onChange={(event) => setPriority(event.target.value)}
        required
        fullWidth
        autoFocus
        helperText={t('RoutingRuleEditDialog.priorityHelperText')}
        slotProps={{ htmlInput: { min: 0 } }}
      />
      <TextField
        select
        label={t('RoutingRuleEditDialog.targetQueueLabel')}
        value={targetQueueId}
        disabled={queuesQuery.isPending}
        onChange={(event) => setTargetQueueId(event.target.value)}
        required
        fullWidth
      >
        {queuesQuery.data?.map((queue) => (
          <MenuItem key={queue.id} value={queue.id}>
            {queue.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label={t('RoutingRuleEditDialog.channelTypeLabel')}
        value={channelType}
        onChange={(event) => setChannelType(event.target.value)}
        fullWidth
        helperText={t('RoutingRuleEditDialog.channelTypeHelperText')}
      >
        <MenuItem value="">{t('RoutingRuleEditDialog.anyChannelOption')}</MenuItem>
        {CHANNEL_TYPES.map((type) => (
          <MenuItem key={type.value} value={type.value}>
            {type.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label={t('RoutingRuleEditDialog.bodyContainsLabel')}
        value={bodyContains}
        onChange={(event) => setBodyContains(event.target.value)}
        fullWidth
        helperText={t('RoutingRuleEditDialog.bodyContainsHelperText')}
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label={t('RoutingRuleEditDialog.activeLabel')}
      />
    </FormDialog>
  )
}
