import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { InboxPage } from './InboxPage'

describe('InboxPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists conversations with resolved customer and channel names', async () => {
    renderAuthenticated(<InboxPage />)
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()
    expect(screen.getByText('Support Telegram')).toBeInTheDocument()
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('filters to an empty list when switching to a status tab with no matches', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('tab', { name: /closed/i }))
    expect(await screen.findByText(/no conversations here/i)).toBeInTheDocument()
  })

  it('"My conversations only" filters out a conversation not assigned to me', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    // The seeded conversation is unassigned, so filtering to "mine"
    // (the logged-in test user's own agent profile — see
    // mocks/handlers/agents.ts's "Mock Self Agent" seed) correctly finds
    // nothing, proving the toggle actually threads assigned_agent_id
    // through to the request rather than being a no-op.
    await user.click(screen.getByRole('switch', { name: /my conversations only/i }))
    expect(await screen.findByText(/no conversations here/i)).toBeInTheDocument()
    expect(screen.queryByText('Grace Blake')).not.toBeInTheDocument()
  })

  it('shows a distinct empty state for a user with no agent profile', async () => {
    server.use(
      http.get(`${API_BASE_URL}/agents`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    // A prior test's `agents` fetch can still be settling when this one
    // starts (React Query dedupes in-flight requests by query key across
    // renders), which would otherwise resolve this test's first render
    // with that stale, non-overridden response — clearing here guarantees
    // the override above is what actually answers this test's fetch.
    queryClient.clear()
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('switch', { name: /my conversations only/i }))
    await waitFor(() => expect(screen.getByText(/no agent profile/i)).toBeInTheDocument())
  })
})
