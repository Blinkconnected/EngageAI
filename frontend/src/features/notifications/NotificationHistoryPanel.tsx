import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Button,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  Switch,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import {
  useDeleteNotificationMutation,
  useMarkAllNotificationsReadMutation,
  useMarkNotificationReadMutation,
  useNotificationsQuery,
} from './api'
import type { Notification } from './types'

const PAGE_STEP = 20
// Same documented, honest limit as MessageThread.tsx's growing-page_size
// "load more" — beyond this, real offset-based paging would be needed.
const MAX_VISIBLE = 100

export function NotificationHistoryPanel() {
  const navigate = useNavigate()
  const [visibleCount, setVisibleCount] = useState(PAGE_STEP)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const notificationsQuery = useNotificationsQuery({
    page: 1,
    page_size: visibleCount,
    unread_only: unreadOnly,
  })
  const markReadMutation = useMarkNotificationReadMutation()
  const markAllReadMutation = useMarkAllNotificationsReadMutation()
  const deleteMutation = useDeleteNotificationMutation()

  if (notificationsQuery.isPending) return <LoadingState label="Loading notifications…" />
  if (notificationsQuery.isError) {
    return (
      <ErrorState error={notificationsQuery.error} onRetry={() => notificationsQuery.refetch()} />
    )
  }

  const { items, total } = notificationsQuery.data
  const hasMore = total > visibleCount && visibleCount < MAX_VISIBLE

  function handleItemClick(notification: Notification) {
    if (!notification.is_read) markReadMutation.mutate(notification.id)
    const conversationId = notification.payload.conversation_id
    if (typeof conversationId === 'string') navigate(`/conversations/${conversationId}`)
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <FormControlLabel
          control={
            <Switch
              checked={unreadOnly}
              onChange={(event) => {
                setUnreadOnly(event.target.checked)
                setVisibleCount(PAGE_STEP)
              }}
            />
          }
          label="Unread only"
        />
        <Button
          size="small"
          disabled={total === 0}
          onClick={() => markAllReadMutation.mutate()}
        >
          Mark all read
        </Button>
      </Stack>

      {items.length === 0 && (
        <EmptyState
          title="No notifications"
          description={
            unreadOnly
              ? "You're all caught up — no unread notifications."
              : 'Notifications about your conversations and workflows will appear here.'
          }
        />
      )}

      {items.map((notification) => (
        <Paper
          key={notification.id}
          variant="outlined"
          sx={{
            p: 1.5,
            bgcolor: notification.is_read ? 'transparent' : 'action.hover',
            cursor: notification.is_read ? 'default' : 'pointer',
          }}
          onClick={() => handleItemClick(notification)}
        >
          <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <Stack sx={{ flexGrow: 1, minWidth: 0 }} spacing={0.5}>
              <Typography variant="body2" sx={{ fontWeight: notification.is_read ? 400 : 600 }}>
                {notification.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {notification.body}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {formatRelativeTime(notification.created_at)}
              </Typography>
            </Stack>
            <Tooltip title="Delete">
              <IconButton
                size="small"
                aria-label={`Delete notification: ${notification.title}`}
                onClick={(event) => {
                  event.stopPropagation()
                  deleteMutation.mutate(notification.id)
                }}
              >
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Paper>
      ))}

      {hasMore && (
        <Box sx={{ textAlign: 'center' }}>
          <Button
            onClick={() => setVisibleCount((count) => Math.min(count + PAGE_STEP, MAX_VISIBLE))}
            disabled={notificationsQuery.isFetching}
          >
            Load more
          </Button>
        </Box>
      )}
    </Stack>
  )
}
