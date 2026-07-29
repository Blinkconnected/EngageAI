import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'

import { apiClient } from '../../shared/api/client'
import { useCurrentUserQuery } from './api'

/** Shown across the top of the app until the workspace is verified.
 *
 * Deliberately an `Alert`, not a modal. The chosen behaviour is that an
 * unverified workspace can be *read* — somebody who has just signed up
 * should be able to look around — so blocking the screen would take
 * away the only thing they are allowed to do. */
export function VerifyEmailBanner() {
  const { t } = useTranslation('session')
  const session = useCurrentUserQuery()
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'throttled' | 'failed'>(
    'idle',
  )

  if (!session.data || session.data.company.verified) return null

  const resend = async () => {
    setState('sending')
    try {
      const { data } = await apiClient.post<{ sent: boolean }>('/auth/resend-verification')
      // `sent: false` is not a failure — it means another link went out
      // moments ago. Saying "failed" would make somebody try again
      // harder, which is exactly what the throttle is there to stop.
      setState(data.sent ? 'sent' : 'throttled')
    } catch {
      setState('failed')
    }
  }

  return (
    <Alert
      severity="warning"
      square
      action={
        state === 'sent' || state === 'throttled' ? undefined : (
          <Button color="inherit" size="small" onClick={resend} disabled={state === 'sending'}>
            {t('VerifyEmailBanner.resend')}
          </Button>
        )
      }
    >
      {state === 'sent' && t('VerifyEmailBanner.sent')}
      {state === 'throttled' && t('VerifyEmailBanner.throttled')}
      {state === 'failed' && t('VerifyEmailBanner.failed')}
      {(state === 'idle' || state === 'sending') &&
        t('VerifyEmailBanner.message', { email: session.data.email })}
    </Alert>
  )
}
