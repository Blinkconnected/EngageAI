import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAppSelector } from '../../app/hooks'
import { selectIsAuthenticated } from '../auth/authSlice'
import { store } from '../../app/store'
import { playNotificationSound, showBrowserNotification } from '../notifications/deliveryEffects'
import {
  NOTIFICATIONS_KEY,
  PREFERENCES_KEY,
  UNREAD_COUNT_KEY,
  useNotificationPreferencesQuery,
} from '../notifications/api'
import { useNotificationToast } from '../notifications/notificationToastContext'
import type { NotificationChannel, NotificationPreference } from '../notifications/types'
import { RealtimeContext } from './context'

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? '/api/v1/ws'
const RECONNECT_DELAY_MS = 3000

interface NotificationFrame {
  type?: string
  notification_type?: string
  title?: string
  body?: string
}

/** Absence of a cached preference (not yet fetched, or never
 * overridden) means enabled — same "opt-out, default-on" behavior the
 * backend itself uses when no preference row exists. */
function isChannelEnabled(
  queryClient: ReturnType<typeof useQueryClient>,
  notificationType: string,
  channel: NotificationChannel,
): boolean {
  const preferences = queryClient.getQueryData<NotificationPreference[]>(PREFERENCES_KEY)
  const preference = preferences?.find(
    (item) => item.notification_type === notificationType && item.channel === channel,
  )
  return preference?.enabled ?? true
}

/**
 * One WebSocket connection per authenticated session, mounted once in
 * AppLayout — not per-conversation, since connecting/disconnecting flips
 * the agent's presence between online/offline (see
 * docs/architecture/notifications.md). Live notification pushes are a
 * convenience that invalidates the notifications/unread-count queries;
 * GET /notifications remains the durable source of truth those queries
 * poll independently either way.
 *
 * Two frame types drive this: `notification` (a brand-new notification —
 * also triggers the browser-notification/sound delivery effects, each
 * gated by that notification_type's cached preference) and
 * `notifications_changed` (read-state changed on *this* user's inbox
 * from some other connection — a mark-read/mark-all-read in another
 * browser tab or device — which only needs a cache refresh, never a
 * sound/popup for something that isn't new).
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const queryClient = useQueryClient()
  // Subscribing here (not just relying on NotificationPreferencesPanel's
  // own query) is what keeps PREFERENCES_KEY populated for the entire
  // authenticated session, in every tab — otherwise a tab that never
  // opened Settings > Notifications > Preferences would read an empty
  // cache in isChannelEnabled() below and silently ignore every saved
  // opt-out (the `?? true` fallback firing unconditionally).
  useNotificationPreferencesQuery()
  const { showToast } = useNotificationToast()
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedIntentionallyRef = useRef(false)

  useEffect(() => {
    if (!isAuthenticated) return undefined

    function connect() {
      const accessToken = store.getState().auth.accessToken
      if (!accessToken) return

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}${WS_BASE_URL}/agent?token=${accessToken}`
      const socket = new WebSocket(url)
      socketRef.current = socket

      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data as string) as NotificationFrame
          if (frame.type === 'notification' || frame.type === 'notifications_changed') {
            void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY })
            void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
          }
          if (frame.type === 'notification' && frame.notification_type && frame.title) {
            // Always shown — the in-app toast is part of the same
            // "always delivered" tier as the bell's badge/history list,
            // not a tunable delivery channel like browser/sound.
            showToast(frame.title, frame.body ?? '')
            if (isChannelEnabled(queryClient, frame.notification_type, 'browser')) {
              showBrowserNotification(frame.title, frame.body ?? '')
            }
            if (isChannelEnabled(queryClient, frame.notification_type, 'sound')) {
              playNotificationSound()
            }
          }
        } catch {
          // Malformed frame — ignore, matches the backend's own
          // "invalid frames are silently ignored" behavior for inbound
          // typing frames.
        }
      }

      socket.onclose = () => {
        if (closedIntentionallyRef.current) return
        reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    closedIntentionallyRef.current = false
    connect()

    return () => {
      closedIntentionallyRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [isAuthenticated, queryClient, showToast])

  const sendTyping = useCallback((conversationId: string, isTyping: boolean) => {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    socket.send(
      JSON.stringify({ type: 'typing', conversation_id: conversationId, is_typing: isTyping }),
    )
  }, [])

  return <RealtimeContext.Provider value={{ sendTyping }}>{children}</RealtimeContext.Provider>
}
