import { useCallback, useState, type ReactNode } from 'react'
import { Alert, AlertTitle, Slide, Stack } from '@mui/material'
import { NotificationToastContext } from './notificationToastContext'

interface ToastNotification {
  id: string
  title: string
  body: string
}

const AUTO_HIDE_MS = 8000

/**
 * Renders live notification pushes as dismissible toasts stacked in the
 * top-right corner — distinct from the bell's badge/history list (passive,
 * requires opening the dropdown) and from the native browser Notification
 * (OS-controlled, only fires when the tab isn't focused and permission was
 * granted). Always shown regardless of the "browser"/"sound" delivery
 * preferences — this is the in-app tier, which (like the badge/history
 * list itself) is never gated by a per-channel toggle. See
 * domain/notification_types.py's NotificationChannel docstring for the
 * backend's matching rationale.
 */
export function NotificationToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastNotification[]>([])

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const showToast = useCallback(
    (title: string, body: string) => {
      const id = `${Date.now()}-${Math.random()}`
      setToasts((current) => [...current, { id, title, body }])
      setTimeout(() => dismiss(id), AUTO_HIDE_MS)
    },
    [dismiss],
  )

  return (
    <NotificationToastContext.Provider value={{ showToast }}>
      {children}
      <Stack
        spacing={1}
        sx={{
          position: 'fixed',
          top: 16,
          left: 16,
          right: 16,
          zIndex: (theme) => theme.zIndex.snackbar,
          width: '100%',
          maxWidth: 360,
          // `left` and `right` are both set so the stack never overflows
          // a narrow viewport (width falls back to the left/right gap
          // instead of the fixed 360 maxWidth); `ml: auto` then pushes it
          // back to hug the right edge once the viewport is wide enough
          // for maxWidth to win.
          ml: 'auto',
        }}
      >
        {toasts.map((toast) => (
          <Slide key={toast.id} direction="left" in mountOnEnter unmountOnExit>
            <Alert
              severity="info"
              variant="filled"
              onClose={() => dismiss(toast.id)}
              sx={{ width: '100%', boxShadow: 3 }}
            >
              <AlertTitle sx={{ mb: toast.body ? undefined : 0 }}>{toast.title}</AlertTitle>
              {toast.body}
            </Alert>
          </Slide>
        ))}
      </Stack>
    </NotificationToastContext.Provider>
  )
}
