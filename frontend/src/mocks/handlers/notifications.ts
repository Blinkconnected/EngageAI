import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Notification } from '../../features/notifications/types'

const SEED_NOTIFICATIONS: Notification[] = [
  {
    id: 'notif-1',
    notification_type: 'conversation.assigned',
    title: 'New conversation assigned',
    body: 'Grace Blake sent a new message.',
    payload: {},
    is_read: false,
    read_at: null,
    created_at: '2026-01-01T00:00:00Z',
  },
]

let notifications: Notification[] = [...SEED_NOTIFICATIONS]

export function resetNotificationsMock() {
  notifications = [...SEED_NOTIFICATIONS]
}

export const notificationsHandlers = [
  http.get(`${API_BASE_URL}/notifications/unread-count`, () =>
    HttpResponse.json({ unread_count: notifications.filter((n) => !n.is_read).length }),
  ),

  http.get(`${API_BASE_URL}/notifications`, () =>
    HttpResponse.json({
      items: notifications,
      total: notifications.length,
      page: 1,
      page_size: 10,
    }),
  ),

  http.post(`${API_BASE_URL}/notifications/:notificationId/read`, ({ params }) => {
    notifications = notifications.map((n) =>
      n.id === params.notificationId ? { ...n, is_read: true, read_at: '2026-01-01T00:00:00Z' } : n,
    )
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE_URL}/notifications/read-all`, () => {
    notifications = notifications.map((n) => ({
      ...n,
      is_read: true,
      read_at: '2026-01-01T00:00:00Z',
    }))
    return new HttpResponse(null, { status: 204 })
  }),
]
