import { Routes, Route } from 'react-router-dom'
import { LoginPage } from '../features/auth/LoginPage'
import { RegisterPage } from '../features/auth/RegisterPage'
import { ProtectedRoute } from '../features/auth/ProtectedRoute'
import { AppLayout } from '../features/layout/AppLayout'
import { RequirePermission } from '../features/layout/RequirePermission'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { AgentsPage } from '../features/agents/AgentsPage'
import { CompanySettingsPage } from '../features/company/CompanySettingsPage'
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
        <Route
          path="agents"
          element={
            <RequirePermission permission="agents.read">
              <AgentsPage />
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
        <Route path="403" element={<ForbiddenPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
