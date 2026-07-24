import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ConversationViewPage } from './ConversationViewPage'

function renderConversationView() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationViewPage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

// "Grace Blake" legitimately renders twice once the page has loaded — once
// in the page header, once in the sidebar's "Customer" field — so it's an
// ambiguous match for getByText/findByText (which require exactly one).
// The Status field is unique and only mounts once the conversation and its
// sidebar have loaded, so it's used as the "page is ready" signal instead.
async function waitForLoaded() {
  return screen.findByLabelText(/^status/i)
}

describe('ConversationViewPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the customer name and the seeded message', async () => {
    renderConversationView()
    await waitForLoaded()
    expect(await screen.findAllByText('Grace Blake')).not.toHaveLength(0)
    expect(await screen.findByText('Hi, I need help with my order.')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderConversationView()
    await waitForLoaded()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('sends a reply and it appears in the thread', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'Sure, happy to help!')
    await user.click(screen.getByRole('button', { name: /send reply/i }))

    expect(await screen.findByText('Sure, happy to help!')).toBeInTheDocument()
  })

  it('changes the conversation status', async () => {
    const user = userEvent.setup()
    renderConversationView()
    const statusField = await waitForLoaded()

    await user.click(statusField)
    await user.click(await screen.findByRole('option', { name: 'Resolved' }))

    await waitFor(() => expect(screen.getByLabelText(/^status/i)).toHaveTextContent('Resolved'))
  })

  it('adds an internal note', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /internal notes/i }))
    await user.type(
      screen.getByPlaceholderText(/add an internal note/i),
      'Customer seems frustrated.',
    )
    await user.click(screen.getByRole('button', { name: /add note/i }))

    expect(await screen.findByText('Customer seems frustrated.')).toBeInTheDocument()
  })
})
