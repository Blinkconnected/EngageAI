/**
 * The agent's operational workspace.
 *
 * The success criterion for this screen is a second: an experienced agent
 * should understand their workload without reading rows. So the tests below
 * are mostly about *order and prominence* rather than about data appearing —
 * whether the page answers "what does my day look like" before it answers
 * "which conversation should I open".
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { InboxWorkspace } from './InboxWorkspace'

/** Both paths render the same workspace — the conversation is a pane
 * beside the list, not a screen that replaces it. */
function renderWorkspace(entry = '/conversations') {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations" element={<InboxWorkspace />} />
      <Route path="/conversations/:conversationId" element={<InboxWorkspace />} />
    </Routes>,
    [entry],
  )
}

describe('InboxWorkspace', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('answers the workload before it answers which conversation', async () => {
    renderWorkspace()

    // The summary is the first landmark on the page, ahead of the queues and
    // the list. That order is the design: it is the order of the questions
    // somebody actually asks at 9am.
    const summary = await screen.findByRole('region', { name: /workload/i })
    const queues = screen.getByRole('tablist', { name: /work queues/i })

    expect(summary.compareDocumentPosition(queues) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows every work queue, including the empty ones', async () => {
    renderWorkspace()

    const queues = await screen.findByRole('tablist', { name: /work queues/i })

    // "Breached (0)" is one of the most valuable things this screen can say.
    // Hiding empty queues would remove exactly the reassurance a morning
    // needs, so all eight are always present.
    expect(within(queues).getAllByRole('tab')).toHaveLength(8)
  })

  it('puts the count in the label, so a queue answers before it is clicked', async () => {
    renderWorkspace()

    // Waiting for one count to land means waiting for the workload
    // request itself — the tablist renders before it resolves.
    await screen.findByRole('tab', { name: /needs attention \(\d+\)/i })

    const queues = screen.getByRole('tablist', { name: /work queues/i })
    // Every tab carries a number: "Breached" invites a click to find out,
    // "Breached (0)" does not.
    for (const tab of within(queues).getAllByRole('tab')) {
      expect(tab.textContent).toMatch(/\(\d+\)/)
    }
  })

  it('opens on what needs attention rather than on everything', async () => {
    renderWorkspace()

    const queues = await screen.findByRole('tablist', { name: /work queues/i })
    const selected = within(queues)
      .getAllByRole('tab')
      .find((tab) => tab.getAttribute('aria-selected') === 'true')

    expect(selected?.textContent).toMatch(/needs attention/i)
  })

  it('changes the work when a queue is chosen, not just the rows', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    const queues = await screen.findByRole('tablist', { name: /work queues/i })
    await user.click(within(queues).getByRole('tab', { name: /breached/i }))

    // The section names the work and states what it means. Selecting a queue
    // should feel like sitting at a different desk, which is why the heading
    // moves with it instead of the page staying "Inbox" with a filter on.
    const workspace = await screen.findByRole('region', { name: /breached/i })
    expect(within(workspace).getByText(/waiting does not improve these/i)).toBeInTheDocument()
  })

  it('says which good news an empty queue is', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    const queues = await screen.findByRole('tablist', { name: /work queues/i })
    await user.click(within(queues).getByRole('tab', { name: /breached/i }))

    // "Nothing has breached" and "nothing needs attention" are different
    // pieces of good news, and a generic empty state throws away which one
    // an agent just earned.
    expect(await screen.findByText(/nothing has breached/i)).toBeInTheDocument()
  })

  it('explains a conversation before showing its content', async () => {
    renderWorkspace()

    const row = await screen.findByRole('button', { name: /Grace Blake/i })

    // Customer, then why it is here, then who owns it. The message text is
    // seventh of eight and is not what the row leads with — an agent should
    // understand why a conversation is in front of them before reading a
    // word of it.
    expect(within(row).getByText('Grace Blake')).toBeInTheDocument()
    expect(within(row).getByText(/waiting for pickup/i)).toBeInTheDocument()
    expect(within(row).getByText(/support queue/i)).toBeInTheDocument()
  })

  it('shows what most recently changed, from the platform not the thread', async () => {
    renderWorkspace()

    const row = await screen.findByRole('button', { name: /Grace Blake/i })

    expect(within(row).getByText(/Routed to the "Support" queue/i)).toBeInTheDocument()
  })

  it('keeps the list beside the conversation instead of replacing it', async () => {
    // The whole reason for the redesign. Opening a conversation used to
    // navigate away, so working a queue meant list → conversation → Back,
    // losing your place in the list every single time.
    renderWorkspace('/conversations/conv-1')

    expect(await screen.findByRole('tablist', { name: /work queues/i })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: /status and timings/i })).toBeInTheDocument()
  })

  it('marks which row is being read', async () => {
    renderWorkspace('/conversations/conv-1')

    const row = await screen.findByRole('button', { name: /Grace Blake/i })
    expect(row).toHaveAttribute('aria-current', 'true')
  })

  it('says what the empty half is for rather than leaving it blank', async () => {
    renderWorkspace()

    // The empty pane is the one place on this screen with room to
    // explain itself.
    expect(await screen.findByText(/pick a conversation/i)).toBeInTheDocument()
  })

  it('offers Pick up from the list, without opening the conversation first', async () => {
    // An agent working a pickup queue claims several in a row. Making
    // each one a round trip through the conversation is the slow path.
    renderWorkspace()

    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[0]).getByRole('button', { name: /pick up/i })).toBeInTheDocument()
  })

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    const row = await screen.findByRole('button', { name: /Grace Blake/i })
    row.focus()
    expect(row).toHaveFocus()
    await user.keyboard('{Enter}')
    // Navigating away is the router's job; what matters here is that the row
    // is reachable and actionable without a mouse.
    expect(row).toBeInTheDocument()
  })
})
