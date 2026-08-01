import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Chip, List, ListItemButton, ListItemText, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useAllChannelsQuery } from '../channels/api'
import { useConversationsQuery } from '../conversations/api'
import type { ConversationStatus } from '../conversations/types'

const STATUS_COLOR: Record<ConversationStatus, 'info' | 'warning' | 'success' | 'default'> = {
  new: 'info',
  waiting: 'warning',
  in_progress: 'info',
  waiting_customer: 'default',
  waiting_agent: 'warning',
  resolved: 'success',
  customer_feedback: 'info',
  closed: 'default',
}

export function CustomerTimelinePanel({ customerId }: { customerId: string }) {
  const { t } = useTranslation('customers')
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

  if (conversationsQuery.isPending)
    return <LoadingState label={t('CustomerTimelinePanel.loadingLabel')} />
  if (conversationsQuery.isError) {
    return (
      <ErrorState error={conversationsQuery.error} onRetry={() => conversationsQuery.refetch()} />
    )
  }

  if (conversationsQuery.data.items.length === 0) {
    return (
      <EmptyState
        title={t('CustomerTimelinePanel.emptyTitle')}
        description={t('CustomerTimelinePanel.emptyDescription')}
      />
    )
  }

  const { total } = conversationsQuery.data

  return (
    <List>
      {total > 50 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          {t('CustomerTimelinePanel.recentCountLabel', { total })}
        </Typography>
      )}
      {conversationsQuery.data.items.map((conversation) => (
        <ListItemButton
          key={conversation.id}
          onClick={() => navigate(`/conversations/${conversation.id}`)}
          sx={{ borderRadius: 2, mb: 0.5 }}
        >
          <ListItemText
            primary={
              channelById.get(conversation.channel_config_id) ??
              t('CustomerTimelinePanel.conversationFallback')
            }
            secondary={
              conversation.last_message_at
                ? t('CustomerTimelinePanel.lastMessageLabel', {
                    time: formatRelativeTime(conversation.last_message_at),
                  })
                : t('CustomerTimelinePanel.startedLabel', {
                    time: formatRelativeTime(conversation.created_at),
                  })
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
