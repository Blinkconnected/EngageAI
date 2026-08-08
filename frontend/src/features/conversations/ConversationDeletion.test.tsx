/**
 * Deleting a conversation takes two people.
 *
 * A conversation is the record of what a company said to a customer.
 * These tests defend the two properties that make removing one
 * accountable rather than merely possible: asking is not deleting, and
 * the reason travels with the request all the way to the decision.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { MOCK_USER } from '../../mocks/handlers/auth'
import { seedDeletionRequest } from '../../mocks/handlers/conversationDeletion'
import { ConversationViewPage } from './ConversationViewPage'
import { DeletionApprovalsPage } from './DeletionApprovalsPage'

const REASON = 'The customer asked us to remove their personal data.'

function renderConversation() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationViewPage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

function withoutPermission(code: string) {
  server.use(
    http.get(`${API_BASE_URL}/auth/me`, () =>
      HttpResponse.json({
        ...MOCK_USER,
        permissions: MOCK_USER.permissions.filter((permission) => permission !== code),
      }),
    ),
  )
  queryClient.clear()
}

describe('Asking for a conversation to be deleted', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('sends a request instead of deleting anything', async () => {
    const user = userEvent.setup()
    renderConversation()

    await user.click(await screen.findByRole('button', { name: /ask to delete/i }))
    await user.type(screen.getByRole('textbox', { name: /why should this be deleted/i }), REASON)
    await user.click(screen.getByRole('button', { name: /send request/i }))

    // The conversation is still on screen, and the banner says what is
    // now true. Somebody who pressed "delete" and saw nothing happen
    // would press it again.
    expect(await screen.findByText(/has asked for this conversation to be deleted/i)).toBeVisible()
  })

  it('says out loud that nothing is deleted yet', async () => {
    const user = userEvent.setup()
    renderConversation()

    await user.click(await screen.findByRole('button', { name: /ask to delete/i }))

    expect(screen.getByText(/nothing is deleted yet/i)).toBeInTheDocument()
  })

  it('will not send a reason nobody could act on', async () => {
    const user = userEvent.setup()
    renderConversation()
    await user.click(await screen.findByRole('button', { name: /ask to delete/i }))

    await user.type(screen.getByRole('textbox', { name: /why should this be deleted/i }), 'spam')

    // "spam" tells the administrator reading this next week nothing.
    expect(screen.getByRole('button', { name: /send request/i })).toBeDisabled()
  })

  it('tells everybody looking at the conversation that deletion was asked for', async () => {
    seedDeletionRequest({ reason: REASON, requested_by_name: 'Ordinary Agent' })
    renderConversation()

    // Not only the person who asked: an agent about to invest in a reply
    // needs to know it may be on its way out, and a second agent needs to
    // know not to ask again.
    const banner = await screen.findByText(/ordinary agent has asked/i)
    expect(banner).toHaveTextContent(REASON)
    expect(screen.queryByRole('button', { name: /ask to delete/i })).not.toBeInTheDocument()
  })

  it('is not offered without permission to ask', async () => {
    withoutPermission('conversations.delete_request')
    renderConversation()

    await screen.findByRole('region', { name: /status and timings/i })
    expect(screen.queryByRole('button', { name: /ask to delete/i })).not.toBeInTheDocument()
  })
})

describe('Deciding on a deletion request', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the reason as the largest thing on the row', async () => {
    seedDeletionRequest({ reason: REASON })
    renderAuthenticated(<DeletionApprovalsPage />)

    // The reason is the whole basis of the decision, so it is prose on
    // the card rather than a truncated cell.
    expect(await screen.findByText(REASON)).toBeInTheDocument()
    expect(screen.getByText(/grace blake/i)).toBeInTheDocument()
    expect(screen.getByText(/asked by ordinary agent/i)).toBeInTheDocument()
  })

  it('warns that approving cannot be undone, and then deletes', async () => {
    const user = userEvent.setup()
    seedDeletionRequest({ reason: REASON })
    renderAuthenticated(<DeletionApprovalsPage />)

    await user.click(await screen.findByRole('button', { name: /approve and delete/i }))
    expect(screen.getByText(/cannot be undone/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^delete the conversation$/i }))

    // Gone from the queue it was waiting in.
    expect(await screen.findByText(/nothing waiting/i)).toBeInTheDocument()
  })

  it('requires a note before a rejection can be sent', async () => {
    const user = userEvent.setup()
    seedDeletionRequest({ reason: REASON })
    renderAuthenticated(<DeletionApprovalsPage />)

    await user.click(await screen.findByRole('button', { name: /^reject$/i }))

    // An approval stands on the request's own reason. A rejection
    // contradicts it, so the person who asked has to learn something.
    expect(screen.getByRole('button', { name: /reject the request/i })).toBeDisabled()
    await user.type(
      screen.getByRole('textbox', { name: /why are you rejecting/i }),
      'We must keep this for the open billing dispute.',
    )
    expect(screen.getByRole('button', { name: /reject the request/i })).toBeEnabled()
  })

  it('keeps the decision and who made it, once it is decided', async () => {
    seedDeletionRequest({
      status: 'rejected',
      reason: REASON,
      decided_by_name: 'Approving Admin',
      decision_note: 'Needed for the billing dispute.',
    })
    const user = userEvent.setup()
    renderAuthenticated(<DeletionApprovalsPage />)

    await user.click(await screen.findByRole('tab', { name: /rejected/i }))

    const decided = await screen.findByText(/approving admin/i)
    expect(decided).toHaveTextContent(/needed for the billing dispute/i)
    // Nothing left to decide — a decided request is a record, not work.
    expect(screen.queryByRole('button', { name: /approve and delete/i })).not.toBeInTheDocument()
  })

  it('separates what is waiting from what has been settled', async () => {
    seedDeletionRequest({ reason: REASON })
    seedDeletionRequest({ status: 'approved', reason: 'Duplicate conversation, merged already.' })
    const user = userEvent.setup()
    renderAuthenticated(<DeletionApprovalsPage />)

    expect(await screen.findByText(REASON)).toBeInTheDocument()
    expect(screen.queryByText(/duplicate conversation/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /approved/i }))

    expect(await screen.findByText(/duplicate conversation/i)).toBeInTheDocument()
  })

  it('says nothing is waiting rather than showing an empty list', async () => {
    renderAuthenticated(<DeletionApprovalsPage />)

    expect(await screen.findByText(/nothing waiting/i)).toBeInTheDocument()
  })

  it('surfaces a request somebody else already decided', async () => {
    const user = userEvent.setup()
    const request = seedDeletionRequest({ reason: REASON })
    renderAuthenticated(<DeletionApprovalsPage />)
    await screen.findByText(REASON)

    // Two administrators open the same queue. The second one must be
    // told, not silently write a second decision over the first.
    request.status = 'approved'
    await user.click(screen.getByRole('button', { name: /approve and delete/i }))
    await user.click(screen.getByRole('button', { name: /^delete the conversation$/i }))

    expect(await screen.findByText(/already been approved/i)).toBeInTheDocument()
  })
})
