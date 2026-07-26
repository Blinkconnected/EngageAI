import { useState } from 'react'
import {
  Alert,
  Card,
  CardContent,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Typography,
} from '@mui/material'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useNotificationPreferencesQuery } from '../../notifications/api'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

/** A company-wide policy layered above each user's own personal
 * preference (Notification Center's Preferences tab) — if the company
 * disables a type here, no user gets it regardless of their own
 * setting. Reuses the existing preferences endpoint purely to source
 * the fixed catalog of (notification_type, label) pairs, since that's
 * already the single source of truth for it. */
export function NotificationsSettingsPanel({ company }: { company: Company }) {
  const preferencesQuery = useNotificationPreferencesQuery()
  const updateMutation = useUpdateCompanyMutation()
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})

  if (preferencesQuery.isPending) return <LoadingState label="Loading notification types…" />
  if (preferencesQuery.isError) {
    return <ErrorState error={preferencesQuery.error} onRetry={() => preferencesQuery.refetch()} />
  }

  const labelByType = new Map<string, string>()
  for (const item of preferencesQuery.data) {
    labelByType.set(item.notification_type, item.label)
  }
  const notificationTypes = [...labelByType.keys()]

  function isEnabled(notificationType: string): boolean {
    return overrides[notificationType] ?? company.settings.notifications?.[notificationType] ?? true
  }

  function handleToggle(notificationType: string, enabled: boolean) {
    const previous = overrides[notificationType]
    setOverrides((current) => ({ ...current, [notificationType]: enabled }))
    updateMutation.mutate(
      // The backend merges the notifications section one level deep
      // (CompanyService._merge_settings), so sending just the changed
      // type is enough — every other type's stored value is preserved
      // server-side, not just optimistically assumed client-side.
      { settings: { notifications: { [notificationType]: enabled } } },
      {
        onError: () =>
          setOverrides((current) => {
            const reverted = { ...current }
            if (previous === undefined) {
              delete reverted[notificationType]
            } else {
              reverted[notificationType] = previous
            }
            return reverted
          }),
      },
    )
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Turn a notification type off company-wide — no agent will receive it, even if they
            personally enabled it in their own preferences.
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}

          <Table size="small" aria-label="Company notification policy">
            <TableBody>
              {notificationTypes.map((notificationType) => (
                <TableRow key={notificationType}>
                  <TableCell>{labelByType.get(notificationType)}</TableCell>
                  <TableCell align="right">
                    <Switch
                      checked={isEnabled(notificationType)}
                      onChange={(event) => handleToggle(notificationType, event.target.checked)}
                      slotProps={{
                        input: { 'aria-label': `Enable ${labelByType.get(notificationType)}` },
                      }}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Stack>
      </CardContent>
    </Card>
  )
}
