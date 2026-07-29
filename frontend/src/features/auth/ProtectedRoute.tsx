import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../app/hooks'
import { useCurrentUserQuery } from '../session/api'
import { usePlatformMeQuery } from '../platform/api'
import { isAxiosError } from 'axios'
import { selectIsAuthenticated } from './authSlice'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { t } = useTranslation('auth')
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const location = useLocation()
  const currentUserQuery = useCurrentUserQuery()
  // `/auth/me` describes a user *within a company*, so it deliberately
  // refuses a platform-administrator token. Without this the app
  // rendered its tenant shell against a failed profile query and showed
  // a blank page — a successful sign-in was indistinguishable from a
  // broken one. Only asked when /auth/me actually 403s, so an ordinary
  // agent never pays for the extra request.
  const tenantForbidden =
    currentUserQuery.isError &&
    isAxiosError(currentUserQuery.error) &&
    currentUserQuery.error.response?.status === 403
  const platformQuery = usePlatformMeQuery({ enabled: tenantForbidden })

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (tenantForbidden && platformQuery.data?.is_platform_admin) {
    return <Navigate to="/platform" replace />
  }

  if (currentUserQuery.isPending || (tenantForbidden && platformQuery.isPending)) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <CircularProgress aria-label={t('ProtectedRoute.loadingWorkspace')} />
      </Box>
    )
  }

  return children
}
