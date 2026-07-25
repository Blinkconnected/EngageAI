import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import CheckCircleOutlinedIcon from '@mui/icons-material/CheckCircleOutlined'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { usePaginationParams } from '../../shared/api/pagination'
import { useConnectionLogsQuery } from './api'
import type { ChannelConnectionLog } from './types'

const EVENT_LABELS: Record<string, string> = {
  created: 'Channel connected',
  credentials_updated: 'Credentials updated',
  activated: 'Activated',
  deactivated: 'Deactivated',
  test_connection_succeeded: 'Test connection succeeded',
  test_connection_failed: 'Test connection failed',
  health_check_initial: 'Initial health check',
  health_check_recovered: 'Health check recovered',
  health_check_became_unhealthy: 'Health check failed',
  send_failed: 'Message send failed',
}

function LevelIcon({ level }: { level: ChannelConnectionLog['level'] }) {
  if (level === 'error') return <ErrorOutlineIcon color="error" fontSize="small" />
  if (level === 'warning') return <ErrorOutlineIcon color="warning" fontSize="small" />
  return <InfoOutlinedIcon color="info" fontSize="small" />
}

export function ConnectionLogsDialog({
  channel,
  onClose,
}: {
  channel: { id: string; display_name: string } | null
  onClose: () => void
}) {
  if (!channel) return null
  return <ConnectionLogsDialogBody channel={channel} onClose={onClose} />
}

function ConnectionLogsDialogBody({
  channel,
  onClose,
}: {
  channel: { id: string; display_name: string }
  onClose: () => void
}) {
  const { page, pageSize, setPage, apiParams } = usePaginationParams(20)
  const logsQuery = useConnectionLogsQuery(channel.id, apiParams)

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Connection logs — {channel.display_name}</DialogTitle>
      <DialogContent>
        {logsQuery.isPending && <LoadingState label="Loading connection logs…" />}
        {logsQuery.isError && (
          <ErrorState error={logsQuery.error} onRetry={() => logsQuery.refetch()} />
        )}
        {logsQuery.data && logsQuery.data.items.length === 0 && (
          <EmptyState
            title="No activity yet"
            description="Connection/credential changes, test connections, health checks, and send failures will show up here."
            icon={<CheckCircleOutlinedIcon fontSize="inherit" />}
          />
        )}
        {logsQuery.data && logsQuery.data.items.length > 0 && (
          <List dense>
            {logsQuery.data.items.map((log) => (
              <ListItem key={log.id} alignItems="flex-start">
                <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
                  <LevelIcon level={log.level} />
                </ListItemIcon>
                <ListItemText
                  primary={EVENT_LABELS[log.event_type] ?? log.event_type}
                  secondary={
                    <Stack component="span" sx={{ display: 'block' }}>
                      <Typography component="span" variant="body2" color="text.secondary">
                        {log.message}
                      </Typography>
                      <Typography component="span" variant="caption" color="text.disabled">
                        {new Date(log.created_at).toLocaleString()}
                      </Typography>
                    </Stack>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {logsQuery.data && logsQuery.data.total > pageSize && (
          <Stack direction="row" spacing={1} sx={{ mr: 'auto' }}>
            <Button size="small" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Newer
            </Button>
            <Button
              size="small"
              disabled={(page + 1) * pageSize >= logsQuery.data.total}
              onClick={() => setPage(page + 1)}
            >
              Older
            </Button>
          </Stack>
        )}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
