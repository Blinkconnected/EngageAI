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

/**
 * Order is the order the columns appear in, weakest interruption first.
 * `push` is last because it is the only one that can reach somebody who
 * isn't looking at the app — worth being the rightmost, most deliberate
 * toggle rather than sitting next to `browser`, which it is often
 * confused with.
 */
export const NOTIFICATION_CHANNELS = ['email', 'browser', 'sound', 'push'] as const
export type NotificationChannel = (typeof NOTIFICATION_CHANNELS)[number]

/** Matches the backend's `NotificationPreferenceItem`. */
export interface NotificationPreference {
  notification_type: string
  label: string
  channel: NotificationChannel
  enabled: boolean
}
