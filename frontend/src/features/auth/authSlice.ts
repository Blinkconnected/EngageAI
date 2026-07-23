import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

const ACCESS_TOKEN_KEY = 'blinkengage.accessToken'
const REFRESH_TOKEN_KEY = 'blinkengage.refreshToken'

export interface AuthUser {
  id: string
  email: string
  fullName: string
  companyId: string
  roles: string[]
}

export interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: AuthUser | null
}

const initialState: AuthState = {
  accessToken: sessionStorage.getItem(ACCESS_TOKEN_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
  user: null,
}

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    loggedIn(
      state,
      action: PayloadAction<{ accessToken: string; refreshToken: string; user: AuthUser }>,
    ) {
      state.accessToken = action.payload.accessToken
      state.refreshToken = action.payload.refreshToken
      state.user = action.payload.user
      sessionStorage.setItem(ACCESS_TOKEN_KEY, action.payload.accessToken)
      localStorage.setItem(REFRESH_TOKEN_KEY, action.payload.refreshToken)
    },
    authTokenRefreshed(
      state,
      action: PayloadAction<{ accessToken: string; refreshToken: string }>,
    ) {
      state.accessToken = action.payload.accessToken
      state.refreshToken = action.payload.refreshToken
      sessionStorage.setItem(ACCESS_TOKEN_KEY, action.payload.accessToken)
      localStorage.setItem(REFRESH_TOKEN_KEY, action.payload.refreshToken)
    },
    loggedOut(state) {
      state.accessToken = null
      state.refreshToken = null
      state.user = null
      sessionStorage.removeItem(ACCESS_TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    },
  },
})

export const { loggedIn, authTokenRefreshed, loggedOut } = authSlice.actions
export default authSlice.reducer

export const selectIsAuthenticated = (state: { auth: AuthState }): boolean =>
  Boolean(state.auth.accessToken)
