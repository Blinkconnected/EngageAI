import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { PlatformRoute } from '../features/platform/PlatformRoute'
import { PlatformLayout } from '../features/platform/PlatformLayout'
import { PlatformCompaniesPage } from '../features/platform/PlatformCompaniesPage'
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
const LoginPage = lazy(() =>
  import('../features/auth/LoginPage').then((m) => ({ default: m.LoginPage })),
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
const RolesPage = lazy(() =>
  import('../features/roles/RolesPage').then((m) => ({ default: m.RolesPage })),
)
const SlaBuilderPage = lazy(() =>
  import('../features/sla/SlaBuilderPage').then((m) => ({ default: m.SlaBuilderPage })),
)
const InboxPage = lazy(() =>
  import('../features/conversations/InboxPage').then((m) => ({ default: m.InboxPage })),
)
const ConversationWorkspacePage = lazy(() =>
  import('../features/conversations/ConversationWorkspacePage').then((m) => ({
    default: m.ConversationWorkspacePage,
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
        </Route>
        <Route path="/feedback/:conversationId" element={<FeedbackPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardPage />} />
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
                <ConversationWorkspacePage />
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
