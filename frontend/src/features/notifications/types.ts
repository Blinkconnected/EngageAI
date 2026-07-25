/** Matches the backend's `NotificationResponse`. */
export interface Notification {
  id: string
  notification_type: string
  title: string
  body: string
  payload: Record<string, unknown>
  is_read: boolean
  read_at: string | null
  created_at: string
}

export const NOTIFICATION_CHANNELS = ['email', 'browser', 'sound'] as const
export type NotificationChannel = (typeof NOTIFICATION_CHANNELS)[number]

/** Matches the backend's `NotificationPreferenceItem`. */
export interface NotificationPreference {
  notification_type: string
  label: string
  channel: NotificationChannel
  enabled: boolean
}
