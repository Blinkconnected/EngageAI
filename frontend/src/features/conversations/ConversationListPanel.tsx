import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Avatar, Box, Chip, Stack, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useCustomerQuery } from '../customers/api'
import { useConversationsQuery } from './api'
import type { Conversation, ConversationStatus } from './types'

const STATUS_COLOR: Record<ConversationStatus, 'info' | 'warning' | 'success' | 'default'> = {
  open: 'info',
  pending: 'warning',
  resolved: 'success',
  closed: 'default',
}

const STATUS_TAB_KEY: Record<ConversationStatus, string> = {
  open: 'tabOpen',
  pending: 'tabPending',
  resolved: 'tabResolved',
  closed: 'tabClosed',
}

function ConversationRow({
  conversation,
  selected,
  onClick,
}: {
  conversation: Conversation
  selected: boolean
  onClick: () => void
}) {
  const { t } = useTranslation('conversationsCore')
  const customerQuery = useCustomerQuery(conversation.customer_id)
  const name = customerQuery.data?.full_name ?? t('ConversationListPanel.loadingCustomerLabel')

  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      aria-current={selected ? 'true' : undefined}
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        width: '100%',
        p: 1.5,
        border: 0,
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: selected ? 'action.selected' : 'transparent',
        textAlign: 'start',
        cursor: 'pointer',
        font: 'inherit',
        color: 'inherit',
        '&:hover': { bgcolor: selected ? 'action.selected' : 'action.hover' },
      }}
    >
      <Avatar sx={{ width: 36, height: 36, fontSize: '0.95rem' }}>
        {name.charAt(0).toUpperCase()}
      </Avatar>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="body2" noWrap sx={{ fontWeight: selected ? 600 : 400 }}>
          {name}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mt: 0.25 }}>
          <Chip
            label={t(`InboxPage.${STATUS_TAB_KEY[conversation.status]}`)}
            size="small"
            color={STATUS_COLOR[conversation.status]}
            sx={{ height: 20 }}
          />
          {conversation.last_message_at && (
            <Typography variant="caption" color="text.secondary" noWrap>
              {formatRelativeTime(conversation.last_message_at)}
            </Typography>
          )}
        </Stack>
      </Box>
    </Box>
  )
}

/** Compact, always-visible conversation list for the 3-pane workspace
 * (`ConversationWorkspacePage`) — a fast way to switch between
 * conversations without losing the open one's context. Deliberately not
 * a re-implementation of the Inbox's full filterable/sortable table:
 * that richer triage view (queue mode, mine-only, unassigned-only, Pick
 * action) stays on the Inbox page, one click away via the back button —
 * this panel only needs a lightweight status quick-filter. */
export function ConversationListPanel({
  selectedConversationId,
  status,
  queueId,
}: {
  selectedConversationId: string | undefined
  status: ConversationStatus
  queueId: string | null
}) {
  const { t } = useTranslation('conversationsCore')
  const navigate = useNavigate()
  const conversationsQuery = useConversationsQuery({
    page: 1,
    page_size: 50,
    status_filter: status,
    queue_id: queueId ?? undefined,
  })

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto' }}>
        {conversationsQuery.isPending && (
          <LoadingState label={t('ConversationListPanel.loadingLabel')} />
        )}
        {conversationsQuery.isError && (
          <ErrorState
            error={conversationsQuery.error}
            onRetry={() => conversationsQuery.refetch()}
          />
        )}
        {conversationsQuery.data?.total === 0 && (
          <Box sx={{ p: 2 }}>
            <EmptyState
              title={t('ConversationListPanel.emptyTitle')}
              description={t('ConversationListPanel.emptyDescription')}
            />
          </Box>
        )}
        {conversationsQuery.data?.items.map((conversation) => (
          <ConversationRow
            key={conversation.id}
            conversation={conversation}
            selected={conversation.id === selectedConversationId}
            onClick={() => navigate(`/conversations/${conversation.id}`, { replace: true })}
          />
        ))}
      </Box>
    </Box>
  )
}
