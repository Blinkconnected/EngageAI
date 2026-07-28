import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { RealtimeContext } from '../realtime/context'
import { MessageThread } from './MessageThread'

function renderWithTyping(conversationId: string, isTyping: boolean) {
  return renderAuthenticated(
    <RealtimeContext.Provider value={{ sendTyping: () => {}, isCustomerTyping: () => isTyping }}>
      <MessageThread conversationId={conversationId} />
    </RealtimeContext.Provider>,
  )
}

describe('MessageThread', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows a live "Customer is typing…" indicator when isCustomerTyping is true', async () => {
    renderWithTyping('conv-1', true)
    expect(await screen.findByText(/customer is typing/i)).toBeInTheDocument()
  })

  it('does not show the typing indicator when isCustomerTyping is false', async () => {
    renderWithTyping('conv-1', false)
    await screen.findByText(/i need help with my order/i) // wait for seeded messages to load first
    expect(screen.queryByText(/customer is typing/i)).not.toBeInTheDocument()
  })

  // The bubble's alignment/background colour alone fail WCAG 1.4.1 (Use
  // of Color) — a visible "Customer"/"You" label is the only thing in
  // the markup that actually names the sender.
  it('labels each bubble with its sender, not just alignment/colour', async () => {
    renderWithTyping('conv-1', false)
    await screen.findByText(/i need help with my order/i)

    expect(screen.getByText('Customer')).toBeInTheDocument()
  })
})
