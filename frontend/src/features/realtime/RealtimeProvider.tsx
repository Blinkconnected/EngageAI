import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAppSelector } from '../../app/hooks'
import { selectIsAuthenticated } from '../auth/authSlice'
import { store } from '../../app/store'
import { NOTIFICATIONS_KEY, UNREAD_COUNT_KEY } from '../notifications/api'
import { RealtimeContext } from './context'

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? '/api/v1/ws'
const RECONNECT_DELAY_MS = 3000

/**
 * One WebSocket connection per authenticated session, mounted once in
 * AppLayout — not per-conversation, since connecting/disconnecting flips
 * the agent's presence between online/offline (see
 * docs/architecture/notifications.md). Live notification pushes are a
 * convenience that invalidates the notifications/unread-count queries;
 * GET /notifications remains the durable source of truth those queries
 * poll independently either way.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const queryClient = useQueryClient()
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
          const frame = JSON.parse(event.data as string) as { type?: string }
          if (frame.type === 'notification') {
            void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY })
            void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
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
  }, [isAuthenticated, queryClient])

  const sendTyping = useCallback((conversationId: string, isTyping: boolean) => {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    socket.send(
      JSON.stringify({ type: 'typing', conversation_id: conversationId, is_typing: isTyping }),
    )
  }, [])

  return <RealtimeContext.Provider value={{ sendTyping }}>{children}</RealtimeContext.Provider>
}
