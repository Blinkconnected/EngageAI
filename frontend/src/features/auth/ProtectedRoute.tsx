import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { useAppSelector } from '../../app/hooks'
import { useCurrentUserQuery } from '../session/api'
import { selectIsAuthenticated } from './authSlice'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const location = useLocation()
  const currentUserQuery = useCurrentUserQuery()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (currentUserQuery.isPending) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <CircularProgress aria-label="Loading your workspace" />
      </Box>
    )
  }

  return children
}
