import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  it('re-arms scroll-to-newest when the open conversation changes', async () => {
    // Opening a conversation must always land on its newest message.
    // `wasNearBottomRef` survives re-renders by design (it must not
    // trigger one), which means it also survives switching conversations
    // in the three-pane workspace — this component's prop changes rather
    // than it remounting. Without the per-conversation reset, an agent
    // who had scrolled up in the previous conversation would open the
    // next one stranded mid-thread instead of at its latest message.
    // The shared mock serves the same seeded thread for any conversation
    // id, which would leave `lastMessageId` unchanged across the switch
    // and stop the scroll effect from ever re-firing. Real conversations
    // always have distinct message ids, so the second one gets its own.
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    server.use(
      http.get(`${API_BASE_URL}/conversations/:conversationId/messages`, ({ params }) => {
        const isSecond = params.conversationId === 'conv-2'
        return HttpResponse.json({
          items: [
            {
              id: isSecond ? 'msg-conv2-1' : 'msg-1',
              conversation_id: params.conversationId,
              direction: 'inbound',
              message_type: 'text',
              status: 'sent',
              delivery_status: 'not_applicable',
              read_status: 'read',
              body: 'Hi, I need help with my order.',
              external_message_id: 'ext-1',
              reply_to_message_id: null,
              message_metadata: {},
              sent_at: '2026-01-01T00:05:00Z',
              delivered_at: null,
              read_at: null,
              created_at: '2026-01-01T00:05:00Z',
              attachments: [],
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        })
      }),
    )

    // Switching happens inside the rendered tree (not via `rerender`,
    // which would re-render without renderAuthenticated's providers), so
    // MessageThread's prop changes exactly as it does in the real
    // three-pane workspace — the component does not remount.
    function SwitchableThread() {
      const [id, setId] = useState('conv-1')
      return (
        <RealtimeContext.Provider value={{ sendTyping: () => {}, isCustomerTyping: () => false }}>
          <button onClick={() => setId('conv-2')}>switch</button>
          <MessageThread conversationId={id} />
        </RealtimeContext.Provider>
      )
    }

    renderAuthenticated(<SwitchableThread />)
    const thread = await screen.findByText(/i need help with my order/i)
    const scrollContainer = thread.closest('.MuiStack-root') as HTMLElement

    // Simulate the agent having scrolled up to read history.
    Object.defineProperty(scrollContainer, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(scrollContainer, 'clientHeight', { value: 400, configurable: true })
    Object.defineProperty(scrollContainer, 'scrollTop', { value: 0, configurable: true })
    scrollContainer.dispatchEvent(new Event('scroll'))

    let scrolledToBottom = false
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      value: () => {
        scrolledToBottom = true
      },
      configurable: true,
      writable: true,
    })

    await userEvent.click(screen.getByRole('button', { name: 'switch' }))
    await screen.findByText(/i need help with my order/i)

    expect(scrolledToBottom).toBe(true)
  })
})
