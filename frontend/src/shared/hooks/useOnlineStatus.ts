import { useEffect, useState } from 'react'
import { onlineManager } from '@tanstack/react-query'

/** Reads the exact same connectivity signal React Query's own mutation/
 * query pause-and-resume logic already uses (`onlineManager`, subscribed
 * to the browser's `online`/`offline` events by default) — not a second,
 * independently-tracked `navigator.onLine` listener, so the UI can never
 * drift out of sync with what actually determines whether a paused
 * mutation is about to retry. See docs/architecture/frontend.md's
 * "Offline support" section. */
export function useOnlineStatus(): boolean {
  const [isOnline, setIsOnline] = useState(() => onlineManager.isOnline())

  useEffect(() => onlineManager.subscribe(setIsOnline), [])

  return isOnline
}
