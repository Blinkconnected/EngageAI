import { Routes, Route } from 'react-router-dom'
import { LoginPage } from '../features/auth/LoginPage'
import { RegisterPage } from '../features/auth/RegisterPage'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { AppLayout } from '../features/layout/AppLayout'
import { RequirePermission } from '../features/layout/RequirePermission'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { AgentsPage } from '../features/agents/AgentsPage'
import { DepartmentsPage } from '../features/departments/DepartmentsPage'
import { ChannelsPage } from '../features/channels/ChannelsPage'
import { InboxPage } from '../features/conversations/InboxPage'
import { ConversationViewPage } from '../features/conversations/ConversationViewPage'
import { CustomersPage } from '../features/customers/CustomersPage'
import { CustomerProfilePage } from '../features/customers/CustomerProfilePage'
import { ErpConfigSettingsPage } from '../features/erp/ErpConfigSettingsPage'
import { CompanySettingsPage } from '../features/company/CompanySettingsPage'
import { ProfilePage } from '../features/profile/ProfilePage'
import { NotificationsPage } from '../features/notifications/NotificationsPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import { ForbiddenPage } from '../pages/ForbiddenPage'
import { NotFoundPage } from '../pages/NotFoundPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
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
        <Route
          path="erp-configs"
          element={
            <RequirePermission permission="erp.manage">
              <ErpConfigSettingsPage />
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
          path="settings/company"
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
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
