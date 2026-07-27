import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Notification, NotificationPreference } from '../../features/notifications/types'
import { NOTIFICATION_CHANNELS } from '../../features/notifications/types'

const SEED_NOTIFICATIONS: Notification[] = [
  {
    id: 'notif-1',
    notification_type: 'conversation.assignment_changed',
    title: 'New conversation assigned',
    body: 'Grace Blake sent a new message.',
    payload: { conversation_id: 'conv-1' },
    is_read: false,
    read_at: null,
    created_at: '2026-01-01T00:00:00Z',
  },
]

const NOTIFICATION_TYPE_CATALOG: { code: string; label: string }[] = [
  { code: 'conversation.assignment_changed', label: 'New conversation assigned' },
  { code: 'message.persisted', label: 'New message received' },
  { code: 'conversation.transferred', label: 'Conversation transferred to you' },
  { code: 'conversation.sla_breached', label: 'SLA breached' },
  { code: 'workflow.notification', label: 'Workflow notifications' },
]

let notifications: Notification[] = [...SEED_NOTIFICATIONS]
let preferenceOverrides = new Map<string, boolean>()

export function resetNotificationsMock() {
  notifications = [...SEED_NOTIFICATIONS]
  preferenceOverrides = new Map()
}

function preferenceKey(notificationType: string, channel: string) {
  return `${notificationType}::${channel}`
}

export const notificationsHandlers = [
  http.get(`${API_BASE_URL}/notifications/unread-count`, () =>
    HttpResponse.json({ unread_count: notifications.filter((n) => !n.is_read).length }),
  ),

  http.get(`${API_BASE_URL}/notifications/preferences`, () => {
    const items: NotificationPreference[] = NOTIFICATION_TYPE_CATALOG.flatMap(({ code, label }) =>
      NOTIFICATION_CHANNELS.map((channel) => ({
        notification_type: code,
        label,
        channel,
        enabled: preferenceOverrides.get(preferenceKey(code, channel)) ?? true,
      })),
    )
    return HttpResponse.json({ items })
  }),

  http.put(`${API_BASE_URL}/notifications/preferences`, async ({ request }) => {
    const payload = (await request.json()) as {
      notification_type: string
      channel: string
      enabled: boolean
    }
    preferenceOverrides.set(
      preferenceKey(payload.notification_type, payload.channel),
      payload.enabled,
    )
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${API_BASE_URL}/notifications`, ({ request }) => {
    const url = new URL(request.url)
    const pageSize = Number(url.searchParams.get('page_size') ?? '20')
    const unreadOnly = url.searchParams.get('unread_only') === 'true'
    const filtered = unreadOnly ? notifications.filter((n) => !n.is_read) : notifications
    return HttpResponse.json({
      items: filtered.slice(0, pageSize),
      total: filtered.length,
      page: 1,
      page_size: pageSize,
    })
  }),

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

  http.delete(`${API_BASE_URL}/notifications/:notificationId`, ({ params }) => {
    notifications = notifications.filter((n) => n.id !== params.notificationId)
    return new HttpResponse(null, { status: 204 })
  }),
]
