import { Divider, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllQueuesQuery } from '../queues/api'
import { useUpdateConversationMutation } from './api'
import { CONVERSATION_STATUSES, type Conversation } from './types'

export function ConversationSidebar({
  conversation,
  customerName,
}: {
  conversation: Conversation
  customerName: string
}) {
  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateConversationMutation(conversation.id)

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)

  return (
    <Stack spacing={2} sx={{ p: 2, width: { xs: '100%', md: 280 }, flexShrink: 0 }}>
      <div>
        <Typography variant="overline" color="text.secondary">
          Customer
        </Typography>
        <Typography variant="subtitle1">{customerName}</Typography>
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

      <TextField
        select
        label="Assigned agent"
        size="small"
        value={conversation.assigned_agent_id ?? ''}
        disabled={agentsQuery.isPending}
        onChange={(event) =>
          updateMutation.mutate({ assigned_agent_id: event.target.value || null })
        }
      >
        <MenuItem value="">Unassigned</MenuItem>
        {agentsQuery.data?.map((agent) => (
          <MenuItem key={agent.id} value={agent.id}>
            {agent.full_name}
          </MenuItem>
        ))}
      </TextField>

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
    </Stack>
  )
}
