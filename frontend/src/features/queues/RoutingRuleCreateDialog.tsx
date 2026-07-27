import { useState } from 'react'
import { MenuItem, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { CHANNEL_TYPES } from '../channels/types'
import { useAllQueuesQuery, useCreateRoutingRuleMutation } from './api'

export function RoutingRuleCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('queues')
  const [priority, setPriority] = useState('100')
  const [targetQueueId, setTargetQueueId] = useState('')
  const [channelType, setChannelType] = useState('')
  const [bodyContains, setBodyContains] = useState('')

  const queuesQuery = useAllQueuesQuery()
  const createMutation = useCreateRoutingRuleMutation()

  function reset() {
    setPriority('100')
    setTargetQueueId('')
    setChannelType('')
    setBodyContains('')
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      {
        priority: Number.parseInt(priority, 10) || 100,
        target_queue_id: targetQueueId,
        conditions: {
          ...(channelType ? { channel_type: channelType } : {}),
          ...(bodyContains ? { body_contains: bodyContains } : {}),
        },
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title={t('RoutingRuleCreateDialog.title')}
      submitLabel={t('RoutingRuleCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('RoutingRuleCreateDialog.priorityLabel')}
        type="number"
        value={priority}
        onChange={(event) => setPriority(event.target.value)}
        required
        fullWidth
        autoFocus
        helperText={t('RoutingRuleCreateDialog.priorityHelperText')}
        slotProps={{ htmlInput: { min: 0 } }}
      />
      <TextField
        select
        label={t('RoutingRuleCreateDialog.targetQueueLabel')}
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
        label={t('RoutingRuleCreateDialog.channelTypeLabel')}
        value={channelType}
        onChange={(event) => setChannelType(event.target.value)}
        fullWidth
        helperText={t('RoutingRuleCreateDialog.channelTypeHelperText')}
      >
        <MenuItem value="">{t('RoutingRuleCreateDialog.anyChannelOption')}</MenuItem>
        {CHANNEL_TYPES.map((type) => (
          <MenuItem key={type.value} value={type.value}>
            {type.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label={t('RoutingRuleCreateDialog.bodyContainsLabel')}
        value={bodyContains}
        onChange={(event) => setBodyContains(event.target.value)}
        fullWidth
        helperText={t('RoutingRuleCreateDialog.bodyContainsHelperText')}
      />
    </FormDialog>
  )
}
