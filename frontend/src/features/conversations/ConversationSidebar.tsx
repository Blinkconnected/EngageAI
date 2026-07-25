import { useState } from 'react'
import { Button, Divider, Link, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useAllQueuesQuery } from '../queues/api'
import { useUpdateConversationMutation } from './api'
import { TransferDialog } from './TransferDialog'
import { CONVERSATION_STATUSES, type Conversation } from './types'

export function ConversationSidebar({
  conversation,
  customerName,
}: {
  conversation: Conversation
  customerName: string
}) {
  const { hasPermission } = usePermissions()
  const canTransfer = hasPermission('conversations.transfer')
  const [transferOpen, setTransferOpen] = useState(false)

  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateConversationMutation(conversation.id)

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)
  const assignedAgent = agentsQuery.data?.find((a) => a.id === conversation.assigned_agent_id)
  const assignedDepartment = departmentsQuery.data?.find(
    (d) => d.id === conversation.department_id,
  )

  return (
    <Stack spacing={2} sx={{ p: 2, width: { xs: '100%', md: 280 }, flexShrink: 0 }}>
      <div>
        <Typography variant="overline" color="text.secondary">
          Customer
        </Typography>
        <Typography variant="subtitle1">
          <Link component={RouterLink} to={`/customers/${conversation.customer_id}`}>
            {customerName}
          </Link>
        </Typography>
      </div>
      <div>
        <Typography variant="overline" color="text.secondary">
          Channel
        </Typography>
        <Typography variant="body2">{channel?.display_name ?? '—'}</Typography>
      </div>

      <Divider />

      <TextField
        select
        label="Status"
        size="small"
        value={conversation.status}
        onChange={(event) =>
          updateMutation.mutate({ status: event.target.value as Conversation['status'] })
        }
      >
        {CONVERSATION_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {status[0].toUpperCase() + status.slice(1)}
          </MenuItem>
        ))}
      </TextField>

      <div>
        <Typography variant="overline" color="text.secondary">
          Assigned to
        </Typography>
        <Typography variant="body2">
          {assignedAgent?.full_name ??
            (assignedDepartment ? `${assignedDepartment.name} (department)` : 'Unassigned')}
        </Typography>
        {/* Reassignment always goes through the Transfer dialog, not a
            free-form dropdown — see TransferDialog.tsx's docstring on why
            (permission gate, history, recipient notification). Hidden
            entirely (not just disabled) for anyone without
            conversations.transfer, matching this feature's RBAC
            requirement rather than only cosmetically discouraging it. */}
        {canTransfer && (
          <Button size="small" sx={{ mt: 0.5 }} onClick={() => setTransferOpen(true)}>
            Transfer…
          </Button>
        )}
      </div>

      <TextField
        select
        label="Queue"
        size="small"
        value={conversation.queue_id ?? ''}
        disabled={queuesQuery.isPending}
        onChange={(event) => updateMutation.mutate({ queue_id: event.target.value || null })}
      >
        <MenuItem value="">No queue</MenuItem>
        {queuesQuery.data?.map((queue) => (
          <MenuItem key={queue.id} value={queue.id}>
            {queue.name}
          </MenuItem>
        ))}
      </TextField>

      {transferOpen && (
        <TransferDialog conversation={conversation} onClose={() => setTransferOpen(false)} />
      )}
    </Stack>
  )
}
