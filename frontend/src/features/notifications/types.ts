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
