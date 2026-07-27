import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert } from '@mui/material'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

const RECONNECTED_MESSAGE_DURATION_MS = 5000

/** A persistent, always-visible bar (not a dismissible toast — losing
 * connectivity affects everything on screen, not one action) shown
 * whenever the browser goes offline, plus a brief confirmation once it
 * comes back. Mounted once in AppLayout, above everything else in the
 * signed-in shell. See docs/architecture/frontend.md's "Offline
 * support" section for what actually keeps working while this is
 * showing (queued message sends) versus what doesn't (everything else,
 * same as before this milestone). */
export function OfflineBanner() {
  const { t } = useTranslation('shared')
  const isOnline = useOnlineStatus()
  const [prevIsOnline, setPrevIsOnline] = useState(isOnline)
  const [showReconnected, setShowReconnected] = useState(false)

  // "Adjusting state when a prop changes" — computed directly during
  // render (React's own recommended pattern for this), not inside an
  // effect, since setting state synchronously in an effect body causes
  // an extra, avoidable render pass.
  if (isOnline !== prevIsOnline) {
    setPrevIsOnline(isOnline)
    setShowReconnected(isOnline)
  }

  useEffect(() => {
    if (!showReconnected) return
    const timeout = setTimeout(() => setShowReconnected(false), RECONNECTED_MESSAGE_DURATION_MS)
    return () => clearTimeout(timeout)
  }, [showReconnected])

  if (!isOnline) {
    return (
      <Alert severity="warning" sx={{ borderRadius: 0 }}>
        {t('OfflineBanner.offlineMessage')}
      </Alert>
    )
  }
  if (showReconnected) {
    return (
      <Alert severity="success" sx={{ borderRadius: 0 }}>
        {t('OfflineBanner.reconnectedMessage')}
      </Alert>
    )
  }
  return null
}
