import { useState } from 'react'
import {
  Badge,
  Box,
  Button,
  Divider,
  IconButton,
  ListItemButton,
  ListItemText,
  Menu,
  Typography,
} from '@mui/material'
import NotificationsOutlinedIcon from '@mui/icons-material/NotificationsOutlined'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import {
  useMarkAllNotificationsReadMutation,
  useMarkNotificationReadMutation,
  useNotificationsQuery,
  useUnreadCountQuery,
} from './api'

export function NotificationBell() {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const unreadCountQuery = useUnreadCountQuery()
  const notificationsQuery = useNotificationsQuery({ page: 1, page_size: 10 })
  const markReadMutation = useMarkNotificationReadMutation()
  const markAllReadMutation = useMarkAllNotificationsReadMutation()

  return (
    <>
      <IconButton
        onClick={(event) => setAnchorEl(event.currentTarget)}
        aria-label={`Notifications${unreadCountQuery.data ? ` (${unreadCountQuery.data} unread)` : ''}`}
      >
        <Badge badgeContent={unreadCountQuery.data ?? 0} color="error">
          <NotificationsOutlinedIcon />
        </Badge>
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { width: 360, maxHeight: 480 } } }}
      >
        <Box
          sx={{
            px: 2,
            py: 1,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Notifications
          </Typography>
          {Boolean(unreadCountQuery.data) && (
            <Button size="small" onClick={() => markAllReadMutation.mutate()}>
              Mark all read
            </Button>
          )}
        </Box>
        <Divider />
        {notificationsQuery.data?.items.length === 0 && (
          <Box sx={{ px: 2 }}>
            <EmptyState title="No notifications" />
          </Box>
        )}
        {notificationsQuery.data?.items.map((notification) => (
          <ListItemButton
            key={notification.id}
            onClick={() => {
              if (!notification.is_read) markReadMutation.mutate(notification.id)
            }}
            sx={{
              alignItems: 'flex-start',
              bgcolor: notification.is_read ? 'transparent' : 'action.hover',
            }}
          >
            <ListItemText
              primary={notification.title}
              secondary={
                <>
                  <Typography variant="body2" component="span" sx={{ display: 'block' }}>
                    {notification.body}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {formatRelativeTime(notification.created_at)}
                  </Typography>
                </>
              }
            />
          </ListItemButton>
        ))}
      </Menu>
    </>
  )
}
