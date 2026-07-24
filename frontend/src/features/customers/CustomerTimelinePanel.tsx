import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Chip, List, ListItemButton, ListItemText } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useAllChannelsQuery } from '../channels/api'
import { useConversationsQuery } from '../conversations/api'
import type { ConversationStatus } from '../conversations/types'

const STATUS_COLOR: Record<ConversationStatus, 'info' | 'warning' | 'success' | 'default'> = {
  open: 'info',
  pending: 'warning',
  resolved: 'success',
  closed: 'default',
}

export function CustomerTimelinePanel({ customerId }: { customerId: string }) {
  const navigate = useNavigate()
  const conversationsQuery = useConversationsQuery({
    page: 1,
    page_size: 50,
    customer_id: customerId,
  })
  const channelsQuery = useAllChannelsQuery()

  const channelById = useMemo(() => {
    const map = new Map<string, string>()
    channelsQuery.data?.forEach((channel) => map.set(channel.id, channel.display_name))
    return map
  }, [channelsQuery.data])

  if (conversationsQuery.isPending) return <LoadingState label="Loading conversation history…" />
  if (conversationsQuery.isError) {
    return (
      <ErrorState error={conversationsQuery.error} onRetry={() => conversationsQuery.refetch()} />
    )
  }

  if (conversationsQuery.data.items.length === 0) {
    return (
      <EmptyState
        title="No conversations yet"
        description="This customer hasn't reached out on any connected channel."
      />
    )
  }

  return (
    <List>
      {conversationsQuery.data.items.map((conversation) => (
        <ListItemButton
          key={conversation.id}
          onClick={() => navigate(`/conversations/${conversation.id}`)}
          sx={{ borderRadius: 2, mb: 0.5 }}
        >
          <ListItemText
            primary={channelById.get(conversation.channel_config_id) ?? 'Conversation'}
            secondary={
              conversation.last_message_at
                ? `Last message ${formatRelativeTime(conversation.last_message_at)}`
                : `Started ${formatRelativeTime(conversation.created_at)}`
            }
          />
          <Chip
            label={conversation.status}
            size="small"
            color={STATUS_COLOR[conversation.status]}
          />
        </ListItemButton>
      ))}
    </List>
  )
}
