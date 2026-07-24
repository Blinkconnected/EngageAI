import axios, { type InternalAxiosRequestConfig } from 'axios'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { authenticated, loggedOut } from '../../features/auth/authSlice'
import { SESSION_QUERY_KEY } from './queryKeys'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const accessToken = store.getState().auth.accessToken
  if (accessToken) {
    config.headers.set('Authorization', `Bearer ${accessToken}`)
  }
  return config
})

let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = store.getState().auth.refreshToken
  if (!refreshToken) return null

  try {
    const response = await axios.post<{ access_token: string; refresh_token: string }>(
      `${API_BASE_URL}/auth/refresh`,
      { refresh_token: refreshToken },
    )
    store.dispatch(
      authenticated({
        accessToken: response.data.access_token,
        refreshToken: response.data.refresh_token,
      }),
    )
    return response.data.access_token
  } catch {
    store.dispatch(loggedOut())
    queryClient.removeQueries({ queryKey: SESSION_QUERY_KEY })
    return null
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null
      })
      const newAccessToken = await refreshPromise
      if (newAccessToken) {
        originalRequest.headers.set('Authorization', `Bearer ${newAccessToken}`)
        return apiClient(originalRequest)
      }
    }
    return Promise.reject(error)
  },
)
