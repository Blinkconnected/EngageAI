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
 * swallow deep links. Somebody following a link to a specific
 * conversation while signed out has to end up at sign-in and then at
 * that conversation, not on a marketing page that discards where they
 * were going.
 */
describe('RootRoute', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the public site at the root when signed out', async () => {
    renderWithProviders(<AppRoutes />, ['/'])

    expect(await screen.findByRole('heading', { level: 1, name: /one place/i })).toBeInTheDocument()
  })

  it('still sends a signed-out visitor from a deep link to sign in', async () => {
    renderWithProviders(<AppRoutes />, ['/agents'])

    // The sign-in form, not the landing page. Losing the destination is
    // the regression this guards against.
    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { level: 1, name: /one place/i }),
      ).not.toBeInTheDocument()
    })
  })

  it('shows the application at the root when signed in', async () => {
    renderAuthenticated(<AppRoutes />, ['/'])

    // The marketing hero must not appear for somebody who is signed in —
    // they asked for their dashboard.
    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { level: 1, name: /one place/i }),
      ).not.toBeInTheDocument()
    })
  })
})
