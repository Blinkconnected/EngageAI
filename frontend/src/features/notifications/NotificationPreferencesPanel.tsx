import { useState } from 'react'
import {
  Alert,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import {
  getBrowserNotificationPermission,
  isBrowserNotificationSupported,
  requestBrowserNotificationPermission,
} from './deliveryEffects'
import { useNotificationPreferencesQuery, useUpdateNotificationPreferenceMutation } from './api'
import { NOTIFICATION_CHANNELS, type NotificationChannel } from './types'

const CHANNEL_LABELS: Record<NotificationChannel, string> = {
  email: 'Email',
  browser: 'Browser',
  sound: 'Sound',
}

export function NotificationPreferencesPanel() {
  const preferencesQuery = useNotificationPreferencesQuery()
  const updateMutation = useUpdateNotificationPreferenceMutation()
  const [browserPermission, setBrowserPermission] = useState(getBrowserNotificationPermission())

  if (preferencesQuery.isPending) return <LoadingState label="Loading preferences…" />
  if (preferencesQuery.isError) {
    return <ErrorState error={preferencesQuery.error} onRetry={() => preferencesQuery.refetch()} />
  }

  const preferences = preferencesQuery.data
  const notificationTypes = [...new Set(preferences.map((item) => item.notification_type))]
  const labelByType = new Map(preferences.map((item) => [item.notification_type, item.label]))

  function isEnabled(notificationType: string, channel: NotificationChannel): boolean {
    return (
      preferences.find(
        (item) => item.notification_type === notificationType && item.channel === channel,
      )?.enabled ?? true
    )
  }

  async function handleToggle(
    notificationType: string,
    channel: NotificationChannel,
    enabled: boolean,
  ) {
    if (channel === 'browser' && enabled && browserPermission !== 'granted') {
      const result = await requestBrowserNotificationPermission()
      setBrowserPermission(result)
      if (result !== 'granted') return // don't record "enabled" if the browser denied it
    }
    updateMutation.mutate({ notification_type: notificationType, channel, enabled })
  }

  return (
    <Stack spacing={2}>
      {!isBrowserNotificationSupported() && (
        <Alert severity="info">Browser notifications aren't supported in this browser.</Alert>
      )}
      {isBrowserNotificationSupported() && browserPermission === 'denied' && (
        <Alert severity="warning">
          Browser notifications are blocked at the browser level. Enable them in this site's
          browser settings to use this channel.
        </Alert>
      )}
      <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="Notification preferences">
          <TableHead>
            <TableRow>
              <TableCell>Notification type</TableCell>
              {NOTIFICATION_CHANNELS.map((channel) => (
                <TableCell key={channel} align="center">
                  {CHANNEL_LABELS[channel]}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {notificationTypes.map((notificationType) => (
              <TableRow key={notificationType}>
                <TableCell>{labelByType.get(notificationType)}</TableCell>
                {NOTIFICATION_CHANNELS.map((channel) => (
                  <TableCell key={channel} align="center">
                    <Switch
                      size="small"
                      checked={isEnabled(notificationType, channel)}
                      disabled={channel === 'browser' && !isBrowserNotificationSupported()}
                      onChange={(event) =>
                        void handleToggle(notificationType, channel, event.target.checked)
                      }
                      slotProps={{
                        input: {
                          'aria-label': `${labelByType.get(notificationType)} via ${CHANNEL_LABELS[channel]}`,
                        },
                      }}
                    />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  )
}
