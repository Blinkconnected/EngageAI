/**
 * The facts an agent reads before typing a word.
 *
 * Every one of these used to be behind a `⋮` menu and a drawer — who the
 * customer is, what the conversation is waiting on, how long it has been
 * waiting, and Pick up, which is the most common action on the screen.
 *
 * The tests are about *what is reachable without opening anything*,
 * because that is the entire change. A test that opened the drawer first
 * would pass just as well against the design this replaces.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ConversationViewPage } from './ConversationViewPage'

function renderConversation() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationViewPage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

function strip() {
  return screen.findByRole('region', { name: /status and timings/i })
}

describe('ConversationHeaderBar', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('says how long, not just what — without anything being opened', async () => {
    renderConversation()

    // A conversation's state without its duration is half a fact.
    // "Waiting" is a shrug; "Waiting 4h" is a decision.
    const facts = await strip()
    for (const label of [/^owner$/i, /^waiting$/i, /^last message$/i, /^opened$/i]) {
      expect(within(facts).getByText(label), `missing ${label}`).toBeInTheDocument()
    }
  })

  it('names the customer without making anybody open a panel', async () => {
    renderConversation()

    expect(await screen.findByRole('link', { name: /grace blake/i })).toBeInTheDocument()
  })

  it('leads with Pick up on a conversation nobody owns', async () => {
    renderConversation()
    await strip()

    // The seeded conversation is queued and unassigned. Claiming it is
    // the only thing anybody does to it, so it is the one action that
    // gets a filled button.
    expect(await screen.findByRole('button', { name: /pick up/i })).toBeInTheDocument()
  })

  it('keeps the settings-shaped fields in the drawer rather than repeating them', async () => {
    renderConversation()
    await strip()

    // Status and queue are re-filing, not replying. They stay one click
    // away — and, just as importantly, the ownership buttons are *not*
    // duplicated in there, because the same button in two places is how
    // a screen stops being trustworthy.
    expect(screen.queryByRole('combobox', { name: /^status/i })).not.toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderConversation()
    await strip()

    expect(await axe(container)).toHaveNoViolations()
  })
})
