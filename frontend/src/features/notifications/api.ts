import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { useAppSelector } from '../../app/hooks'
import { selectIsAuthenticated } from '../auth/authSlice'
import type { Page, PageParams } from '../../shared/api/pagination'
import type { Notification, NotificationChannel, NotificationPreference } from './types'

const NOTIFICATIONS_KEY = ['notifications']
const UNREAD_COUNT_KEY = ['notifications', 'unread-count']
const PREFERENCES_KEY = ['notifications', 'preferences']

async function fetchNotifications(
  params: PageParams & { unread_only?: boolean },
): Promise<Page<Notification>> {
  const { data } = await apiClient.get<Page<Notification>>('/notifications', { params })
  return data
}

async function fetchUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<{ unread_count: number }>('/notifications/unread-count')
  return data.unread_count
}

async function markRead(notificationId: string): Promise<void> {
  await apiClient.post(`/notifications/${notificationId}/read`)
}

async function markAllRead(): Promise<void> {
  await apiClient.post('/notifications/read-all')
}

async function deleteNotification(notificationId: string): Promise<void> {
  await apiClient.delete(`/notifications/${notificationId}`)
}

async function fetchPreferences(): Promise<NotificationPreference[]> {
  const { data } = await apiClient.get<{ items: NotificationPreference[] }>(
    '/notifications/preferences',
  )
  return data.items
}

async function updatePreference(params: {
  notification_type: string
  channel: NotificationChannel
  enabled: boolean
}): Promise<void> {
  await apiClient.put('/notifications/preferences', params)
}

/** These are the durable source of truth per docs/architecture/frontend.md
 * — polled independently of the WS live push, which is an at-most-once
 * convenience on top, never the only trigger for a refetch. */
export function useNotificationsQuery(params: PageParams & { unread_only?: boolean }) {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  return useQuery({
    queryKey: [...NOTIFICATIONS_KEY, params],
    queryFn: () => fetchNotifications(params),
    enabled: isAuthenticated,
    placeholderData: (previousData) => previousData,
    refetchInterval: 30_000,
  })
}

export function useUnreadCountQuery() {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  return useQuery({
    queryKey: UNREAD_COUNT_KEY,
    queryFn: fetchUnreadCount,
    enabled: isAuthenticated,
    refetchInterval: 30_000,
  })
}

export function useNotificationPreferencesQuery() {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  return useQuery({
    queryKey: PREFERENCES_KEY,
    queryFn: fetchPreferences,
    enabled: isAuthenticated,
  })
}

export function useMarkNotificationReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY })
      void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
    },
  })
}

export function useMarkAllNotificationsReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY })
      void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
    },
  })
}

export function useDeleteNotificationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteNotification,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY })
      void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
    },
  })
}

export function useUpdateNotificationPreferenceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updatePreference,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY })
    },
  })
}

export { NOTIFICATIONS_KEY, PREFERENCES_KEY, UNREAD_COUNT_KEY }
