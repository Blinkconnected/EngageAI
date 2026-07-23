import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { useAppDispatch } from '../../app/hooks'
import { loggedIn, loggedOut, type AuthUser } from './authSlice'

interface LoginRequest {
  email: string
  password: string
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  user: AuthUser
}

async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>('/auth/login', payload)
  return data
}

export function useLoginMutation() {
  const dispatch = useAppDispatch()
  return useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      dispatch(
        loggedIn({
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          user: data.user,
        }),
      )
    },
  })
}

export function useLogout() {
  const dispatch = useAppDispatch()
  return async () => {
    try {
      await apiClient.post('/auth/logout')
    } finally {
      dispatch(loggedOut())
    }
  }
}
