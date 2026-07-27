import { useState } from 'react'
import { FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
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
      title="Edit routing rule"
      submitLabel="Save changes"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label="Priority"
        type="number"
        value={priority}
        onChange={(event) => setPriority(event.target.value)}
        required
        fullWidth
        autoFocus
        helperText="Lower numbers are evaluated first — the first matching rule wins."
        slotProps={{ htmlInput: { min: 0 } }}
      />
      <TextField
        select
        label="Route to queue"
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
        label="Channel type"
        value={channelType}
        onChange={(event) => setChannelType(event.target.value)}
        fullWidth
        helperText="Leave as 'Any channel' to match every channel type."
      >
        <MenuItem value="">Any channel</MenuItem>
        {CHANNEL_TYPES.map((type) => (
          <MenuItem key={type.value} value={type.value}>
            {type.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Message contains"
        value={bodyContains}
        onChange={(event) => setBodyContains(event.target.value)}
        fullWidth
        helperText="Optional — matches if the first message contains this text (case-insensitive)."
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
