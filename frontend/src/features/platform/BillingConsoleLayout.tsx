import { useTranslation } from 'react-i18next'
import { ConsoleShell } from './ConsoleShell'

/**
 * The billing console: running the revenue system.
 *
 * Its own surface rather than a tab beside Companies and Email. Pricing,
 * profiles, per-company terms — and, as they ship, invoices and collections —
 * are one job with one mental model: what things cost and who owes what.
 * Suspending a company is a different job that happens to need the same
 * authority.
 *
 * Mounted under `/platform/billing` rather than at `/billing`, for two
 * reasons. `/billing` is the *tenant's* own billing page and must stay theirs.
 * And nesting inherits `PlatformRoute`, so this console cannot be reached
 * without platform authority even if somebody adds a section here and forgets
 * to guard it — the same principle the API router uses for its gated routers.
 */
export function BillingConsoleLayout() {
  const { t } = useTranslation('platform')

  return (
    <ConsoleShell
      title={t('BillingConsole.title')}
      subtitle={t('BillingConsole.subtitle')}
      // One section today. Invoices and collections are built in the API and
      // have no screen yet; a nav link to a page that does not exist is worse
      // than an obviously short nav.
      sections={[{ to: '/platform/billing', label: t('BillingConsole.pricing'), end: true }]}
      sibling={{ to: '/platform', label: t('BillingConsole.platformConsole') }}
    />
  )
}
