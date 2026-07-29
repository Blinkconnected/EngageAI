import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { useAppSelector } from '../../app/hooks'
import { selectIsAuthenticated } from '../auth/authSlice'
import { usePlatformMeQuery } from './api'

/** Gates the platform console. A tenant user reaching `/platform` is
 * sent back to their own workspace rather than shown an error — they
 * followed a link that simply isn't theirs. */
export function PlatformRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const profileQuery = usePlatformMeQuery({ enabled: isAuthenticated })

  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (profileQuery.isPending) {
    return (
      <Box sx={{ minHeight: '100dvh', display: 'grid', placeItems: 'center' }}>
        <CircularProgress />
      </Box>
    )
  }
  if (profileQuery.isError || !profileQuery.data?.is_platform_admin) {
    return <Navigate to="/" replace />
  }
  return children
}
