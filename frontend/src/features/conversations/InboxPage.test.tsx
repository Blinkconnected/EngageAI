import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { MOCK_USER } from '../../mocks/handlers/auth'
import { InboxPage } from './InboxPage'

describe('InboxPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists conversations with resolved customer and channel names', async () => {
    renderAuthenticated(<InboxPage />)
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()
    // The channel column shows an icon, not the channel's display name —
    // its accessible name is the channel *type* label (see
    // ConversationCells.tsx's ChannelIcon), matching the seeded
    // conversation's channel_config_id ("c1" -> channel_type "telegram").
    expect(screen.getByLabelText('Telegram')).toBeInTheDocument()
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

  it('Queue filter mode threads the selected queue id through to the request', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('button', { name: 'Queue' }))
    const queueField = await screen.findByLabelText(/^queue$/i)

    // The seeded conversation belongs to "General" (see
    // mocks/handlers/conversations.ts) — selecting it keeps the row.
    await user.click(queueField)
    await user.click(await screen.findByRole('option', { name: 'General' }))
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()

    // Selecting the other seeded queue ("VIP") proves queue_id actually
    // reached the request rather than being a no-op filter.
    await user.click(screen.getByLabelText(/^queue$/i))
    await user.click(await screen.findByRole('option', { name: 'VIP' }))
    expect(await screen.findByText(/no conversations here/i)).toBeInTheDocument()
    expect(screen.queryByText('Grace Blake')).not.toBeInTheDocument()
  })

  it('has no detectable accessibility violations in Queue filter mode', async () => {
    const user = userEvent.setup()
    const { container } = renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('button', { name: 'Queue' }))
    await screen.findByLabelText(/^queue$/i)

    expect(await axe(container)).toHaveNoViolations()
  })

  it('shows a Pick action on a queued, unassigned conversation in Queue mode, and picking it removes it from the Unassigned-only view', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('button', { name: 'Queue' }))
    await user.click(screen.getByRole('switch', { name: /unassigned only/i }))
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()

    const row = (await screen.findByText('Grace Blake')).closest('[role="row"]')
    expect(row).not.toBeNull()
    await user.click(within(row as HTMLElement).getByLabelText('Pick'))

    // Picking assigns it to the caller, so it drops out of the
    // Unassigned-only view without waiting for the next poll.
    await waitFor(() => expect(screen.queryByText('Grace Blake')).not.toBeInTheDocument())
    expect(await screen.findByText(/no conversations here/i)).toBeInTheDocument()
  })

  it('hides the Pick action without the conversations.pick permission', async () => {
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'conversations.pick'),
        }),
      ),
    )
    queryClient.clear()
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('button', { name: 'Queue' }))
    await user.click(screen.getByRole('switch', { name: /unassigned only/i }))
    await screen.findByText('Grace Blake')

    expect(screen.queryByLabelText('Pick')).not.toBeInTheDocument()
  })

  it('a 409 pick conflict shows an error and immediately refetches the queue-filtered list', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('button', { name: 'Queue' }))
    await user.click(screen.getByRole('switch', { name: /unassigned only/i }))
    const row = (await screen.findByText('Grace Blake')).closest('[role="row"]')
    expect(row).not.toBeNull()

    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/pick`, () =>
        HttpResponse.json({ detail: 'Already claimed by another agent.' }, { status: 409 }),
      ),
      // Simulates the conflicting agent's pick having already landed. This
      // response is only ever reachable if the 409 handler forces an
      // immediate refetch — waiting for the Inbox's own 10s queue-mode
      // poll instead would blow past this test's async-query timeout
      // (asyncUtilTimeout: 5000, see test/setup.ts), so a passing
      // assertion below only holds when the refetch really is immediate.
      http.get(`${API_BASE_URL}/conversations`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    await user.click(within(row as HTMLElement).getByLabelText('Pick'))

    expect(await screen.findByText(/already claimed by another agent/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Grace Blake')).not.toBeInTheDocument())
  })
})
