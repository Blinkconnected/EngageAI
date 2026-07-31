import { useTranslation } from 'react-i18next'
import { ConsoleShell } from './ConsoleShell'

/**
 * The billing console: running the revenue system.
 *
 * Its own surface rather than a tab beside Companies and Email. Revenue,
 * invoices, payments, the ledger, collections and pricing are one job with one
 * mental model: what things cost, what was billed, and who owes what.
 * Suspending a company for abuse is a different job that happens to need the
 * same authority.
 *
 * The sections are ordered the way a finance day runs rather than
 * alphabetically or by how the API is laid out: open on the numbers, work
 * through the documents, follow the money, then chase what did not arrive.
 * Pricing sits last because it is the least frequent — a rate is set once and
 * then read for months.
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
      sections={[
        { to: '/platform/billing', label: t('BillingConsole.revenue'), end: true },
        { to: '/platform/billing/invoices', label: t('BillingConsole.invoices') },
        { to: '/platform/billing/payments', label: t('BillingConsole.payments') },
        { to: '/platform/billing/ledger', label: t('BillingConsole.ledger') },
        { to: '/platform/billing/collections', label: t('BillingConsole.collections') },
        { to: '/platform/billing/pricing', label: t('BillingConsole.pricing') },
      ]}
      sibling={{ to: '/platform', label: t('BillingConsole.platformConsole') }}
    />
  )
}
