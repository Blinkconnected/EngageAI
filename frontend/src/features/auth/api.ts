import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { SESSION_QUERY_KEY } from '../../shared/api/queryKeys'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import type { UserProfile } from '../session/types'
import { authenticated, loggedOut, selectRefreshToken } from './authSlice'

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

interface LoginRequest {
  email: string
  password: string
}

interface RegisterRequest {
  company_name: string
  owner_full_name: string
  owner_email: string
  owner_password: string
  /** ISO 3166-1 alpha-2. Sets the billing currency, and is fixed
   * afterwards — re-denominating issued invoices is never safe. */
  country_code?: string
}

interface RegisterResponse {
  user: UserProfile
  tokens: TokenResponse
}

async function login(payload: LoginRequest): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', payload)
  return data
}

async function register(payload: RegisterRequest): Promise<RegisterResponse> {
  const { data } = await apiClient.post<RegisterResponse>('/auth/register', payload)
  return data
}

export function useLoginMutation() {
  const dispatch = useAppDispatch()
  return useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      dispatch(authenticated({ accessToken: data.access_token, refreshToken: data.refresh_token }))
    },
  })
}

export function useRegisterMutation() {
  const dispatch = useAppDispatch()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: register,
    onSuccess: (data) => {
      dispatch(
        authenticated({
          accessToken: data.tokens.access_token,
          refreshToken: data.tokens.refresh_token,
        }),
      )
      // Register already returned the full profile — avoid an immediate,
      // redundant GET /auth/me round trip for it.
      queryClient.setQueryData(SESSION_QUERY_KEY, data.user)
    },
  })
}

export function useLogout() {
  const dispatch = useAppDispatch()
  const queryClient = useQueryClient()
  const refreshToken = useAppSelector(selectRefreshToken)

  return async () => {
    try {
      if (refreshToken) {
        await apiClient.post('/auth/logout', { refresh_token: refreshToken })
      }
    } finally {
      dispatch(loggedOut())
      queryClient.removeQueries({ queryKey: SESSION_QUERY_KEY })
    }
  }
}


export interface CountryOption {
  code: string
  name: string
  currency: string
  currency_symbol: string
}

/** Countries this installation can bill in.
 *
 * Fetched rather than hardcoded in the client: the list is whichever
 * countries the billing engine has prices for, and a form offering one
 * it does not would create a customer nobody discovers is unbillable
 * until the month closes. */
export function useCountriesQuery() {
  return useQuery({
    queryKey: ['countries'],
    queryFn: async () => {
      const { data } = await apiClient.get<CountryOption[]>('/auth/countries')
      return data
    },
    // The list changes when the product enters a new market, not during
    // a session.
    staleTime: Infinity,
  })
}
