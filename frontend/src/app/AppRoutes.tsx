import { lazy, Suspense } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { useAppSelector } from './hooks'
import { selectIsAuthenticated } from '../features/auth/authSlice'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { PlatformRoute } from '../features/platform/PlatformRoute'
import { PlatformLayout } from '../features/platform/PlatformLayout'
import { BillingConsoleLayout } from '../features/platform/BillingConsoleLayout'
import { PlatformCompaniesPage } from '../features/platform/PlatformCompaniesPage'
import { CompanyUsersPage } from '../features/platform/CompanyUsersPage'
import { PlatformCompanyBillingPage } from '../features/platform/PlatformCompanyBillingPage'
import { PlatformMailPage } from '../features/platform/PlatformMailPage'
import { PlatformPaymentProvidersPage } from '../features/platform/PlatformPaymentProvidersPage'
import { PlatformHealthPage } from '../features/platform/PlatformHealthPage'
import { PlatformPricingPage } from '../features/platform/PlatformPricingPage'
import { RevenueDashboardPage } from '../features/billingops/RevenueDashboardPage'
import { InvoicesPage } from '../features/billingops/InvoicesPage'
import { PaymentsPage } from '../features/billingops/PaymentsPage'
import { LedgerPage } from '../features/billingops/LedgerPage'
import { CollectionsPage } from '../features/billingops/CollectionsPage'
import { CompanyBillingWorkspace } from '../features/billingops/CompanyBillingWorkspace'
import { AppLayout } from '../features/layout/AppLayout'
import { RequirePermission } from '../features/layout/RequirePermission'
import { RequireErpEnabled } from '../features/layout/RequireErpEnabled'
import { LoadingState } from '../shared/components/LoadingState'
import { ForbiddenPage } from '../pages/ForbiddenPage'
import { NotFoundPage } from '../pages/NotFoundPage'

// Every page is its own chunk, not one 1.9 MB bundle — the two routes
// outside ProtectedRoute (`/login`, `/feedback/:conversationId`, the
// latter emailed straight to end customers as a CSAT link) used to ship
// the entire agent console — @mui/x-data-grid, @mui/x-charts + d3, every
// settings/reports/onboarding screen, both locale bundles — just to
// render a sign-in form or a 4.8 KB feedback form. React.lazy splits
// each route's own component into a chunk Vite emits separately; nothing
// here changes what's imported, only when.
const HelpPage = lazy(() =>
  import('../features/help/HelpPage').then((m) => ({ default: m.HelpPage })),
)
const LandingPage = lazy(() =>
  import('../features/marketing/LandingPage').then((m) => ({ default: m.LandingPage })),
)
const LoginPage = lazy(() =>
  import('../features/auth/LoginPage').then((m) => ({ default: m.LoginPage })),
)
const VerifyEmailPage = lazy(() =>
  import('../features/auth/VerifyEmailPage').then((m) => ({ default: m.VerifyEmailPage })),
)
const RegisterPage = lazy(() =>
  import('../features/auth/RegisterPage').then((m) => ({ default: m.RegisterPage })),
)
const DashboardPage = lazy(() =>
  import('../features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const AgentsPage = lazy(() =>
  import('../features/agents/AgentsPage').then((m) => ({ default: m.AgentsPage })),
)
const DepartmentsPage = lazy(() =>
  import('../features/departments/DepartmentsPage').then((m) => ({ default: m.DepartmentsPage })),
)
const ChannelsPage = lazy(() =>
  import('../features/channels/ChannelsPage').then((m) => ({ default: m.ChannelsPage })),
)
const StatusPage = lazy(() =>
  import('../features/status/StatusPage').then((m) => ({ default: m.StatusPage })),
)
const QueuesPage = lazy(() =>
  import('../features/queues/QueuesPage').then((m) => ({ default: m.QueuesPage })),
)
const ServicesPage = lazy(() =>
  import('../features/services/ServicesPage').then((m) => ({ default: m.ServicesPage })),
)
const RolesPage = lazy(() =>
  import('../features/roles/RolesPage').then((m) => ({ default: m.RolesPage })),
)
const SlaBuilderPage = lazy(() =>
  import('../features/sla/SlaBuilderPage').then((m) => ({ default: m.SlaBuilderPage })),
)
// The agent's operational workspace. Replaces the conversation grid: the
// Inbox answers "what does my day look like" before "which conversation
// should I open", and a table could only ever answer the second.
const InboxPage = lazy(() =>
  import('../features/conversations/InboxWorkspace').then((m) => ({
    default: m.InboxWorkspace,
  })),
)
const ConversationViewPage = lazy(() =>
  import('../features/conversations/ConversationViewPage').then((m) => ({
    default: m.ConversationViewPage,
  })),
)
const CustomersPage = lazy(() =>
  import('../features/customers/CustomersPage').then((m) => ({ default: m.CustomersPage })),
)
const CustomerProfilePage = lazy(() =>
  import('../features/customers/CustomerProfilePage').then((m) => ({
    default: m.CustomerProfilePage,
  })),
)
const ErpConfigSettingsPage = lazy(() =>
  import('../features/erp/ErpConfigSettingsPage').then((m) => ({
    default: m.ErpConfigSettingsPage,
  })),
)
const CompanySettingsPage = lazy(() =>
  import('../features/company/CompanySettingsPage').then((m) => ({
    default: m.CompanySettingsPage,
  })),
)
const OnboardingWizardPage = lazy(() =>
  import('../features/onboarding/OnboardingWizardPage').then((m) => ({
    default: m.OnboardingWizardPage,
  })),
)
const ProfilePage = lazy(() =>
  import('../features/profile/ProfilePage').then((m) => ({ default: m.ProfilePage })),
)
const NotificationsPage = lazy(() =>
  import('../features/notifications/NotificationsPage').then((m) => ({
    default: m.NotificationsPage,
  })),
)
const ChangelogPage = lazy(() =>
  import('../features/changelog/ChangelogPage').then((m) => ({ default: m.ChangelogPage })),
)
const FeedbackPage = lazy(() =>
  import('../features/feedback/FeedbackPage').then((m) => ({ default: m.FeedbackPage })),
)
const BillingPage = lazy(() =>
  import('../features/billing/BillingPage').then((m) => ({ default: m.BillingPage })),
)
const IntelligencePage = lazy(() =>
  import('../features/intelligence/IntelligencePage').then((m) => ({
    default: m.IntelligencePage,
  })),
)
const ReportsPage = lazy(() =>
  import('../features/reports/ReportsPage').then((m) => ({ default: m.ReportsPage })),
)

function LazyPageFallback() {
  return <LoadingState />
}

export function AppRoutes() {
  return (
    <Suspense fallback={<LazyPageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        {/* Unauthenticated: the link arrives in an inbox and is often
            opened on a different device from the one that signed up. */}
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/changelog" element={<ChangelogPage />} />

        {/* The platform console. Outside ProtectedRoute/AppLayout on
            purpose: a platform operator has no company, so the tenant
            shell's navigation (Inbox, Customers, Reports…) would be a
            dozen links that all 403 for them. */}
        <Route
          path="/platform"
          element={
            <PlatformRoute>
              <PlatformLayout />
            </PlatformRoute>
          }
        >
          <Route index element={<PlatformCompaniesPage />} />
          {/* One company's user accounts. Nested here rather than under
              the billing console: restoring somebody's access is running
              the installation, not running the revenue system. */}
          <Route path="companies/:companyId/users" element={<CompanyUsersPage />} />
          <Route path="mail" element={<PlatformMailPage />} />
          <Route path="payments" element={<PlatformPaymentProvidersPage />} />
          <Route path="health" element={<PlatformHealthPage />} />
        </Route>

        {/* The billing console. A separate surface from the platform
            console — running the revenue system and running the
            installation are different jobs — but nested under `/platform`
            so it inherits `PlatformRoute`. A new top-level route would be
            a new chance to forget the guard, and `/billing` belongs to the
            tenant's own billing page. */}
        <Route
          path="/platform/billing"
          element={
            <PlatformRoute>
              <BillingConsoleLayout />
            </PlatformRoute>
          }
        >
          {/* The console opens on the numbers rather than on the rate
              editor. A finance module's front page is what the business
              earned; a settings page's front page is a form. */}
          <Route index element={<RevenueDashboardPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="payments" element={<PaymentsPage />} />
          <Route path="ledger" element={<LedgerPage />} />
          <Route path="collections" element={<CollectionsPage />} />
          {/* One company's money: standing, month to date, projection and
              invoice history. */}
          <Route path="companies/:companyId" element={<CompanyBillingWorkspace />} />
          {/* Pricing keeps its own branch. Deciding what a customer is
              charged and chasing what they owe are different jobs done by
              different people, and the per-company pricing screen is a
              different screen from the per-company billing workspace. */}
          <Route path="pricing" element={<PlatformPricingPage />} />
          <Route path="pricing/companies/:companyId" element={<PlatformCompanyBillingPage />} />
        </Route>
        <Route path="/feedback/:conversationId" element={<FeedbackPage />} />
        <Route path="/" element={<RootRoute />}>
          <Route index element={<DashboardPage />} />
          <Route path="help" element={<HelpPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route
            path="onboarding"
            element={
              <RequirePermission permission="company.manage">
                <OnboardingWizardPage />
              </RequirePermission>
            }
          />
          <Route
            path="agents"
            element={
              <RequirePermission permission="agents.read">
                <AgentsPage />
              </RequirePermission>
            }
          />
          <Route
            path="departments"
            element={
              <RequirePermission permission="departments.read">
                <DepartmentsPage />
              </RequirePermission>
            }
          />
          <Route
            path="conversations"
            element={
              <RequirePermission permission="conversations.read">
                <InboxPage />
              </RequirePermission>
            }
          />
          <Route
            path="conversations/:conversationId"
            element={
              <RequirePermission permission="conversations.read">
                <ConversationViewPage />
              </RequirePermission>
            }
          />
          <Route
            path="customers"
            element={
              <RequirePermission permission="customers.read">
                <CustomersPage />
              </RequirePermission>
            }
          />
          <Route
            path="customers/:customerId"
            element={
              <RequirePermission permission="customers.read">
                <CustomerProfilePage />
              </RequirePermission>
            }
          />
          {/* A customer's own billing. `billing.read` is on Owner and
              Admin; what a company spends is not every agent's business. */}
          <Route
            path="billing"
            element={
              <RequirePermission permission="billing.read">
                <BillingPage />
              </RequirePermission>
            }
          />
          <Route
            path="erp-configs"
            element={
              <RequirePermission permission="erp.manage">
                <RequireErpEnabled>
                  <ErpConfigSettingsPage />
                </RequireErpEnabled>
              </RequirePermission>
            }
          />
          <Route
            path="channels"
            element={
              <RequirePermission permission="channels.read">
                <ChannelsPage />
              </RequirePermission>
            }
          />
          <Route
            path="status"
            element={
              <RequirePermission permission="channels.read">
                <StatusPage />
              </RequirePermission>
            }
          />
          <Route
            path="queues"
            element={
              <RequirePermission permission="queues.read">
                <QueuesPage />
              </RequirePermission>
            }
          />
          <Route
            path="services"
            element={
              <RequirePermission permission="queues.read">
                <ServicesPage />
              </RequirePermission>
            }
          />
          <Route
            path="roles"
            element={
              <RequirePermission permission="roles.manage">
                <RolesPage />
              </RequirePermission>
            }
          />
          <Route
            path="sla"
            element={
              <RequirePermission permission="sla_policies.read">
                <SlaBuilderPage />
              </RequirePermission>
            }
          />
          <Route
            path="settings/company/:tab?"
            element={
              <RequirePermission permission="company.manage">
                <CompanySettingsPage />
              </RequirePermission>
            }
          />
          <Route
            path="intelligence"
            element={
              <RequirePermission permission="intelligence.read">
                <IntelligencePage />
              </RequirePermission>
            }
          />
          <Route
            path="reports/:tab?"
            element={
              <RequirePermission permission="reports.read">
                <ReportsPage />
              </RequirePermission>
            }
          />
          <Route path="403" element={<ForbiddenPage />} />
          {/* Matched first for a signed-in user (more specific than the
              top-level "*" below), so an unmatched URL keeps the sidebar/
              top bar/footer instead of dropping them onto a bare page. */}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
        {/* Fallback for a signed-out visitor hitting an unmatched URL —
            ProtectedRoute above would just redirect them to /login anyway,
            so this only ever renders for someone with no session at all. */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}

/**
 * What an anonymous visitor sees at the root.
 *
 * Until now `/` was inside `ProtectedRoute`, so anybody arriving without
 * a session was bounced straight to a sign-in form — which tells
 * somebody evaluating the product nothing about what it is. The root is
 * now the public site for signed-out visitors and the dashboard for
 * everybody else.
 *
 * **Only the exact root changes.** A signed-out visitor deep-linking to
 * `/agents` still goes to sign-in and is returned there afterwards,
 * because showing marketing to somebody who asked for a specific screen
 * would lose their destination. That is why this checks the pathname
 * rather than simply branching on authentication.
 */
function RootRoute() {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const location = useLocation()

  if (!isAuthenticated && location.pathname === '/') {
    return <LandingPage />
  }

  return (
    <ProtectedRoute>
      <AppLayout />
    </ProtectedRoute>
  )
}
