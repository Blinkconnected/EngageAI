import { Routes, Route } from 'react-router-dom'
import { LoginPage } from '../features/auth/LoginPage'
import { RegisterPage } from '../features/auth/RegisterPage'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { AppLayout } from '../features/layout/AppLayout'
import { RequirePermission } from '../features/layout/RequirePermission'
import { RequireErpEnabled } from '../features/layout/RequireErpEnabled'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { AgentsPage } from '../features/agents/AgentsPage'
import { DepartmentsPage } from '../features/departments/DepartmentsPage'
import { ChannelsPage } from '../features/channels/ChannelsPage'
import { StatusPage } from '../features/status/StatusPage'
import { QueuesPage } from '../features/queues/QueuesPage'
import { RolesPage } from '../features/roles/RolesPage'
import { SlaBuilderPage } from '../features/sla/SlaBuilderPage'
import { InboxPage } from '../features/conversations/InboxPage'
import { ConversationWorkspacePage } from '../features/conversations/ConversationWorkspacePage'
import { CustomersPage } from '../features/customers/CustomersPage'
import { CustomerProfilePage } from '../features/customers/CustomerProfilePage'
import { ErpConfigSettingsPage } from '../features/erp/ErpConfigSettingsPage'
import { CompanySettingsPage } from '../features/company/CompanySettingsPage'
import { OnboardingWizardPage } from '../features/onboarding/OnboardingWizardPage'
import { ProfilePage } from '../features/profile/ProfilePage'
import { NotificationsPage } from '../features/notifications/NotificationsPage'
import { ChangelogPage } from '../features/changelog/ChangelogPage'
import { FeedbackPage } from '../features/feedback/FeedbackPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import { ForbiddenPage } from '../pages/ForbiddenPage'
import { NotFoundPage } from '../pages/NotFoundPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/changelog" element={<ChangelogPage />} />
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
  )
}
