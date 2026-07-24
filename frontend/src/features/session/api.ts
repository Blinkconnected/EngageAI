import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { SESSION_QUERY_KEY } from '../../shared/api/queryKeys'
import { useAppSelector } from '../../app/hooks'
import { selectIsAuthenticated } from '../auth/authSlice'
import type { UserProfile } from './types'

export { SESSION_QUERY_KEY }

async function fetchCurrentUser(): Promise<UserProfile> {
  const { data } = await apiClient.get<UserProfile>('/auth/me')
  return data
}

/**
 * The single source of truth for "who is this and what can they do" — see
 * docs/architecture/frontend.md's Authentication flow section. `/auth/login`
 * and `/auth/refresh` return tokens only; this query is what resolves them
 * into a profile, roles, and the effective permission set.
 */
export function useCurrentUserQuery() {
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  return useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: fetchCurrentUser,
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
  })
}
