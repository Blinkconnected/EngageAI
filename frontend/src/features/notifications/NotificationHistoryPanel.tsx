import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  FormControlLabel,
  IconButton,
  ListItemButton,
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
  const { t } = useTranslation('notifications')
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

  if (notificationsQuery.isPending) {
    return <LoadingState label={t('NotificationHistoryPanel.loadingLabel')} />
  }
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
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: 'center', justifyContent: 'space-between' }}
      >
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
          label={t('NotificationHistoryPanel.unreadOnlyLabel')}
        />
        <Button size="small" disabled={total === 0} onClick={() => markAllReadMutation.mutate()}>
          {t('NotificationHistoryPanel.markAllReadButton')}
        </Button>
      </Stack>

      {items.length === 0 && (
        <EmptyState
          title={t('NotificationHistoryPanel.emptyStateTitle')}
          description={
            unreadOnly
              ? t('NotificationHistoryPanel.emptyStateDescriptionUnread')
              : t('NotificationHistoryPanel.emptyStateDescriptionAll')
          }
        />
      )}

      {items.map((notification) => (
        <Paper
          key={notification.id}
          variant="outlined"
          sx={{ bgcolor: notification.is_read ? 'transparent' : 'action.hover' }}
        >
          {/* The row and the delete action are SIBLINGS, not
              parent/child — nesting the IconButton inside the
              ListItemButton would put a <button> inside a <button>,
              which is invalid and breaks keyboard/screen-reader
              activation of the inner control. */}
          <Stack direction="row" spacing={0} sx={{ alignItems: 'stretch' }}>
            <ListItemButton
              onClick={() => handleItemClick(notification)}
              sx={{ flexGrow: 1, minWidth: 0, alignItems: 'flex-start', py: 1.5, px: 1.5 }}
            >
              <Stack sx={{ minWidth: 0 }} spacing={0.5}>
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
            </ListItemButton>
            <Tooltip title={t('NotificationHistoryPanel.deleteTooltip')}>
              <IconButton
                size="small"
                aria-label={t('NotificationHistoryPanel.deleteNotificationAriaLabel', {
                  title: notification.title,
                })}
                onClick={() => deleteMutation.mutate(notification.id)}
                sx={{ alignSelf: 'flex-start', mt: 1.5, mr: 1.5 }}
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
            {t('NotificationHistoryPanel.loadMoreButton')}
          </Button>
        </Box>
      )}
    </Stack>
  )
}
