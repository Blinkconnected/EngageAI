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
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { usePaginationParams } from '../../shared/api/pagination'
import { useConnectionLogsQuery } from './api'
import type { ChannelConnectionLog } from './types'

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
  const { t } = useTranslation('channelsCore')
  const { page, pageSize, setPage, apiParams } = usePaginationParams(20)
  const logsQuery = useConnectionLogsQuery(channel.id, apiParams)

  const EVENT_LABELS: Record<string, string> = {
    created: t('ConnectionLogsDialog.eventCreated'),
    credentials_updated: t('ConnectionLogsDialog.eventCredentialsUpdated'),
    activated: t('ConnectionLogsDialog.eventActivated'),
    deactivated: t('ConnectionLogsDialog.eventDeactivated'),
    test_connection_succeeded: t('ConnectionLogsDialog.eventTestConnectionSucceeded'),
    test_connection_failed: t('ConnectionLogsDialog.eventTestConnectionFailed'),
    health_check_initial: t('ConnectionLogsDialog.eventHealthCheckInitial'),
    health_check_recovered: t('ConnectionLogsDialog.eventHealthCheckRecovered'),
    health_check_became_unhealthy: t('ConnectionLogsDialog.eventHealthCheckBecameUnhealthy'),
    send_failed: t('ConnectionLogsDialog.eventSendFailed'),
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('ConnectionLogsDialog.title', { name: channel.display_name })}</DialogTitle>
      <DialogContent>
        {logsQuery.isPending && <LoadingState label={t('ConnectionLogsDialog.loadingLabel')} />}
        {logsQuery.isError && (
          <ErrorState error={logsQuery.error} onRetry={() => logsQuery.refetch()} />
        )}
        {logsQuery.data && logsQuery.data.items.length === 0 && (
          <EmptyState
            title={t('ConnectionLogsDialog.emptyStateTitle')}
            description={t('ConnectionLogsDialog.emptyStateDescription')}
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
              {t('ConnectionLogsDialog.newerButton')}
            </Button>
            <Button
              size="small"
              disabled={(page + 1) * pageSize >= logsQuery.data.total}
              onClick={() => setPage(page + 1)}
            >
              {t('ConnectionLogsDialog.olderButton')}
            </Button>
          </Stack>
        )}
        <Button onClick={onClose}>{t('ConnectionLogsDialog.closeButton')}</Button>
      </DialogActions>
    </Dialog>
  )
}
