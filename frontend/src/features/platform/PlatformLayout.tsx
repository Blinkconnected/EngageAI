import { useTranslation } from 'react-i18next'
import { ConsoleShell } from './ConsoleShell'

/**
 * The platform console: running the installation.
 *
 * Companies and the mail transport — who is on this deployment and whether it
 * can send. Pricing used to live here and no longer does; it moved to the
 * billing console next door, because setting rates and suspending a company
 * are different jobs even though the same authority covers both.
 */
export function PlatformLayout() {
  const { t } = useTranslation('platform')

  return (
    <ConsoleShell
      title={t('PlatformLayout.title')}
      subtitle={t('PlatformLayout.subtitle')}
      sections={[
        { to: '/platform', label: t('PlatformLayout.companies'), end: true },
        { to: '/platform/mail', label: t('PlatformLayout.mail') },
        { to: '/platform/payments', label: t('PlatformLayout.payments') },
      ]}
      sibling={{ to: '/platform/billing', label: t('PlatformLayout.billingConsole') }}
    />
  )
}
