import { createContext, useContext } from 'react'

export interface NotificationToastContextValue {
  showToast: (title: string, body: string) => void
}

export const NotificationToastContext = createContext<NotificationToastContextValue | null>(null)

export function useNotificationToast(): NotificationToastContextValue {
  const context = useContext(NotificationToastContext)
  if (!context) {
    throw new Error('useNotificationToast must be used within a NotificationToastProvider')
  }
  return context
}
