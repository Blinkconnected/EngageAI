import { describe, expect, it, beforeEach } from 'vitest'
import reducer, {
  authenticated,
  loggedOut,
  selectIsAuthenticated,
  selectRefreshToken,
} from './authSlice'

describe('authSlice', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('stores tokens on authenticated and persists them', () => {
    const initial = { accessToken: null, refreshToken: null }
    const next = reducer(
      initial,
      authenticated({ accessToken: 'access-1', refreshToken: 'refresh-1' }),
    )

    expect(next.accessToken).toBe('access-1')
    expect(next.refreshToken).toBe('refresh-1')
    expect(sessionStorage.getItem('blinkengage.accessToken')).toBe('access-1')
    expect(localStorage.getItem('blinkengage.refreshToken')).toBe('refresh-1')
  })

  it('clears tokens on loggedOut', () => {
    const initial = { accessToken: 'access-1', refreshToken: 'refresh-1' }
    const next = reducer(initial, loggedOut())

    expect(next.accessToken).toBeNull()
    expect(next.refreshToken).toBeNull()
    expect(sessionStorage.getItem('blinkengage.accessToken')).toBeNull()
    expect(localStorage.getItem('blinkengage.refreshToken')).toBeNull()
  })

  it('derives isAuthenticated from the access token only', () => {
    expect(selectIsAuthenticated({ auth: { accessToken: 'x', refreshToken: null } })).toBe(true)
    expect(selectIsAuthenticated({ auth: { accessToken: null, refreshToken: 'x' } })).toBe(false)
  })

  it('selects the refresh token', () => {
    expect(selectRefreshToken({ auth: { accessToken: null, refreshToken: 'refresh-1' } })).toBe(
      'refresh-1',
    )
  })
})
