import type { ReactElement } from 'react'
import { Provider } from 'react-redux'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import { store } from '../app/store'
import { queryClient } from '../app/queryClient'
import { AppThemeProvider } from '../app/AppThemeProvider'

/**
 * Renders a component with the app's real store/query client singletons,
 * WITHOUT dispatching `authenticated` first — for public, unauthenticated
 * surfaces (e.g. LoginPage and anything mounted on it) where
 * `renderAuthenticated` would be wrong (a component that redirects once
 * signed in, like LoginPage, would never render its unauthenticated
 * content under that helper). Callers must reset `store`/`queryClient` in
 * their own `afterEach` — see renderAuthenticated's own doc comment.
 */
export function renderWithProviders(ui: ReactElement, initialEntries: string[] = ['/']) {
  return render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <AppThemeProvider>
          <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
        </AppThemeProvider>
      </QueryClientProvider>
    </Provider>,
  )
}
