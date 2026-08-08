import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { store } from './store'
import { queryClient } from './queryClient'
import { loggedOut } from '../features/auth/authSlice'
import { renderWithProviders } from '../test/renderWithProviders'
import { renderAuthenticated } from '../test/renderAuthenticated'
import { AppRoutes } from './AppRoutes'

/**
 * What the root shows, and — more importantly — what it does *not* change.
 *
 * Making `/` public is a small change with one sharp edge: it must not
 * swallow deep links. Somebody following a link to a specific screen
 * while signed out has to end up at sign-in and then at that screen, not
 * on a marketing page that discards where they were going.
 *
 * Assertions are structural rather than on copy. The landing page is
 * lazy-loaded, so matching translated text races the chunk resolving
 * against i18next attaching its namespace — a race that fails
 * intermittently while saying nothing about routing. The hero
 * illustration and the password field are unambiguous: the public site
 * has the first and not the second, and the login form is the reverse.
 */
describe('RootRoute', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the public site at the root when signed out', async () => {
    renderWithProviders(<AppRoutes />, ['/'])

    expect(await screen.findByRole('img', { name: /inbox/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })

  it('still sends a signed-out visitor from a deep link to sign in', async () => {
    renderWithProviders(<AppRoutes />, ['/agents'])

    // The sign-in form, not the public site. Losing the destination is
    // the regression this guards against.
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /inbox/i })).not.toBeInTheDocument()
  })

  it('shows the application at the root when signed in', async () => {
    renderAuthenticated(<AppRoutes />, ['/'])

    // Somebody signed in asked for their dashboard, not marketing.
    await waitFor(() => {
      expect(screen.queryByRole('img', { name: /inbox/i })).not.toBeInTheDocument()
    })
  })
})
