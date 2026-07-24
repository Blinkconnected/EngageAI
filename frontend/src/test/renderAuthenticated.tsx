import type { ReactElement } from 'react'
import { Provider } from 'react-redux'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import { store } from '../app/store'
import { queryClient } from '../app/queryClient'
import { AppThemeProvider } from '../app/AppThemeProvider'
import { authenticated } from '../features/auth/authSlice'

/**
 * Renders a component as an already-authenticated user, using the app's
 * real store/query client singletons (dispatching `authenticated` first so
 * `usePermissions`/`useCurrentUserQuery` resolve against MSW's `/auth/me`
 * handler exactly as they would in the real app). Callers must reset
 * `store`/`queryClient` in their own `afterEach` — see App.test.tsx.
 */
export function renderAuthenticated(ui: ReactElement) {
  store.dispatch(
    authenticated({ accessToken: 'mock-access-token', refreshToken: 'mock-refresh-token' }),
  )

  return render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <AppThemeProvider>
          <MemoryRouter>{ui}</MemoryRouter>
        </AppThemeProvider>
      </QueryClientProvider>
    </Provider>,
  )
}
