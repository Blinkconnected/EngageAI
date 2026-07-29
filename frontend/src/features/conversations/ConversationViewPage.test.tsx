import { afterEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { onlineManager } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { apiClient } from '../../shared/api/client'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { MOCK_USER } from '../../mocks/handlers/auth'
import { MOCK_CUSTOMER } from '../../mocks/handlers/customers'
import { MOCK_CONVERSATION_SUMMARY, MOCK_REPLY_SUGGESTION } from '../../mocks/handlers/ai'
import { CONVERSATION_KEY } from './api'
import type { Conversation } from './types'
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
  return screen.findByRole('tab', { name: /messages/i })
}

/** Customer details are no longer a permanent column — they open from
 * the conversation's ⋮ menu as an overlay, so the chat keeps the full
 * width whenever they're closed. Any assertion about the details panel
 * has to open it first, exactly as an agent now does. */
async function openDetails() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /conversation actions/i }))
  await user.click(await screen.findByRole('menuitem', { name: /conversation details/i }))
  return screen.findByLabelText(/^status/i)
}


describe('ConversationViewPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    onlineManager.setOnline(true)
  })

  it('keeps customer details out of the way until the agent asks for them', async () => {
    // The point of the change: the chat gets the full width, and the
    // details panel is not occupying it in the meantime.
    renderConversationView()
    await waitForLoaded()

    expect(screen.queryByRole('combobox', { name: /^status/i })).not.toBeInTheDocument()

    await openDetails()

    expect(screen.getByRole('combobox', { name: /^status/i })).toBeInTheDocument()
  })

  it('closes the details panel again, giving the chat its width back', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await waitForLoaded()
    await openDetails()

    await user.click(screen.getByRole('button', { name: /close conversation details/i }))

    await waitFor(() =>
      expect(screen.queryByRole('combobox', { name: /^status/i })).not.toBeInTheDocument(),
    )
  })

  it('shows the customer name and the seeded message', async () => {
    renderConversationView()
    await openDetails()
    expect(await screen.findAllByText('Grace Blake')).not.toHaveLength(0)
    expect(await screen.findByText('Hi, I need help with my order.')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderConversationView()
    await openDetails()
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

  it('does not yank a scrolled-up reader back to the bottom when a new message arrives', async () => {
    // jsdom reports scrollHeight/clientHeight/scrollTop as 0 by default
    // (no real layout), which MessageThread's own "am I near the bottom"
    // check would read as "yes" — this simulates a reader who has
    // genuinely scrolled up to read history by overriding those three
    // properties before the new message arrives.
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    const scrollContainer = screen
      .getByText('Hi, I need help with my order.')
      .closest('.MuiStack-root') as HTMLElement
    Object.defineProperty(scrollContainer, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(scrollContainer, 'clientHeight', { value: 400, configurable: true })
    Object.defineProperty(scrollContainer, 'scrollTop', { value: 0, configurable: true })
    scrollContainer.dispatchEvent(new Event('scroll'))

    const scrollIntoViewSpy = vi.fn()
    // Every element in jsdom needs this stubbed — MessageThread's own
    // effect optional-chains the call specifically because jsdom has no
    // native implementation at all.
    Element.prototype.scrollIntoView = scrollIntoViewSpy

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'New message while scrolled up')
    await user.click(screen.getByRole('button', { name: /send reply/i }))
    await screen.findByText('New message while scrolled up')

    expect(scrollIntoViewSpy).not.toHaveBeenCalled()
  })

  it('queues a reply while offline and sends it once back online', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    onlineManager.setOnline(false)
    await user.type(screen.getByPlaceholderText(/write a reply/i), 'Sent once reconnected')
    await user.click(screen.getByRole('button', { name: /send reply/i }))

    expect(await screen.findByText(/you're offline.*queued/i)).toBeInTheDocument()

    onlineManager.setOnline(true)

    await waitFor(() =>
      expect(screen.queryByText(/you're offline.*queued/i)).not.toBeInTheDocument(),
    )
    expect(screen.getByPlaceholderText(/write a reply/i)).toHaveValue('')
  })

  it('surfaces a diagnosable error when the channel provider rejects a send', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'TRIGGER_SEND_FAILURE')
    await user.click(screen.getByRole('button', { name: /send reply/i }))

    expect(await screen.findByText(/message not delivered/i)).toBeInTheDocument()
    expect(screen.getByText('Failed to send')).toBeInTheDocument()
  })

  it('changes the conversation status', async () => {
    const user = userEvent.setup()
    renderConversationView()
    const statusField = await openDetails()

    await user.click(statusField)
    await user.click(await screen.findByRole('option', { name: 'Resolved' }))

    await waitFor(() => expect(screen.getByLabelText(/^status/i)).toHaveTextContent('Resolved'))
  })

  it('gives the sidebar its own scroll container instead of overflowing into the page', async () => {
    // Previously `overflowY: 'visible'` / `maxHeight: 'none'` on desktop
    // — the sidebar had no scroll container of its own there at all, so
    // a tall sidebar would overflow the row and drag the whole page
    // (including the message list) into scrolling together. The wrapper
    // Box (ConversationViewPage.tsx, one level above ConversationSidebar's
    // own root Stack) is what carries the scroll containment.
    renderConversationView()
    const statusField = await openDetails()
    const sidebarRoot = statusField.closest('.MuiStack-root') as HTMLElement
    const wrapperBox = sidebarRoot.parentElement as HTMLElement

    expect(wrapperBox).toHaveStyle({ overflowY: 'auto' })
  })

  it('never lets the composer shrink, so it stays visible while the message thread scrolls', async () => {
    // The composer (ReplyBox) is a static-flow sibling of MessageThread's
    // own flexGrow/overflowY:auto scroll container inside one minHeight:0
    // flex column — flexShrink: 0 is the actual "always stay pinned at
    // the bottom" contract (see ReplyBox.tsx's own comment): without it,
    // a tall composer (stacked error alerts, attachment chips) has no
    // declared floor and could get squeezed instead of always keeping
    // its full height with MessageThread absorbing the remaining space.
    renderConversationView()
    await openDetails()
    const composerRoot = screen.getByPlaceholderText(/write a reply/i).closest(
      '.MuiBox-root',
    ) as HTMLElement

    expect(composerRoot).toHaveStyle({ flexShrink: '0' })
  })

  // The seeded conversation (conv-1) starts unassigned — this is exactly
  // what an agent lands on after being paged by an SLA-breach or
  // autopilot-handoff notification, which deep-links straight here with
  // no way back to the Inbox's own Pick row action.
  it('claims an unassigned conversation via the sidebar Pick button', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await openDetails()

    const pickButton = await screen.findByRole('button', { name: /pick up/i })
    await user.click(pickButton)

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /pick up/i })).not.toBeInTheDocument(),
    )
  })

  // jsdom's FormData/File polyfill doesn't preserve File.name through a
  // real multipart round trip (verified independently: even a bare
  // `new Request(..., {body: formData}).formData()` loses it in this
  // environment) — content_type does survive, though, which is what
  // AttachmentList actually branches on to choose image-vs-document
  // rendering, so these assert on that rendering decision rather than on
  // filename text a real browser would preserve but jsdom can't.
  //
  // The inline *image* preview specifically isn't covered here: it fetches
  // its blob eagerly on mount, and jsdom's Blob doesn't implement
  // `.stream()`, which MSW's Response construction needs — an unrelated
  // tooling gap (confirmed independent of this app's code), not something
  // a test workaround can route around. AttachmentList.test.tsx covers the
  // image-vs-document rendering decision directly with the network layer
  // mocked out; the real fetch-and-render path is covered by live
  // verification against the production Docker stack in an actual browser.
  it('sends a reply with a document attachment showing a size and download button', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    const file = new File(['%PDF-1.4 fake pdf bytes'], 'invoice.pdf', {
      type: 'application/pdf',
    })
    await user.upload(screen.getByLabelText(/attach a file/i, { selector: 'input' }), file)
    await waitFor(() => expect(screen.getByRole('button', { name: /send reply/i })).toBeEnabled())

    await user.click(screen.getByRole('button', { name: /send reply/i }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^download/i })).toBeInTheDocument(),
    )
    // Size text ("9 B", "1.2 KB", ...) from formatFileSize, proving the
    // document row rendered with real metadata, not just a bare button.
    expect(screen.getByText(/^\d+(\.\d+)?\s?(B|KB|MB|GB)$/)).toBeInTheDocument()
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

  it("shows the customer's internal rating summary in the sidebar once rated", async () => {
    renderConversationView()
    await openDetails()
    expect(screen.queryByText(/based on \d+ internal ratings/i)).not.toBeInTheDocument()

    await apiClient.post(`/customers/${MOCK_CUSTOMER.id}/ratings`, { stars: 4 })
    await queryClient.invalidateQueries({ queryKey: ['customers'] })

    expect(await screen.findByText(/based on 1 internal ratings/i)).toBeInTheDocument()
  })

  // The seeded conversation (see mocks/handlers/conversations.ts) starts
  // queued and unassigned — these exercise the Release button, which only
  // ever appears once *something* has assigned it. Picking it directly
  // through the mock's real /pick endpoint (rather than reaching into the
  // mock module's internal state) keeps these tests exercising the same
  // request path InboxPage.test.tsx's Pick-flow tests do.
  describe('Release', () => {
    async function pickTheConversation() {
      await apiClient.post('/conversations/conv-1/pick')
      await queryClient.invalidateQueries({ queryKey: CONVERSATION_KEY('conv-1') })
    }

    it('is hidden while the conversation is unassigned', async () => {
      renderConversationView()
      await openDetails()
      expect(screen.queryByRole('button', { name: /^release$/i })).not.toBeInTheDocument()
    })

    it('appears once assigned, and releasing it clears the assignment', async () => {
      const user = userEvent.setup()
      renderConversationView()
      await openDetails()

      await pickTheConversation()
      expect(await screen.findByText('Mock Self Agent')).toBeInTheDocument()
      const releaseButton = await screen.findByRole('button', { name: /^release$/i })

      await user.click(releaseButton)

      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /^release$/i })).not.toBeInTheDocument(),
      )
      expect(await screen.findByText('Unassigned')).toBeInTheDocument()
    })

    it('has no detectable accessibility violations once shown', async () => {
      const { container } = renderConversationView()
      await openDetails()
      await pickTheConversation()
      await screen.findByRole('button', { name: /^release$/i })

      expect(await axe(container)).toHaveNoViolations()
    })

    it('is hidden without the conversations.release permission even when assigned', async () => {
      server.use(
        http.get(`${API_BASE_URL}/auth/me`, () =>
          HttpResponse.json({
            ...MOCK_USER,
            permissions: MOCK_USER.permissions.filter((code) => code !== 'conversations.release'),
          }),
        ),
      )
      queryClient.clear()
      renderConversationView()
      await openDetails()

      await pickTheConversation()
      await screen.findByText('Mock Self Agent')

      expect(screen.queryByRole('button', { name: /^release$/i })).not.toBeInTheDocument()
    })

    it('is hidden for a conversation assigned to someone else without conversations.transfer', async () => {
      // Mirrors the backend's own authorization rule
      // (ConversationService.release()): conversations.release alone
      // only lets you release your OWN conversation. Assigned here to
      // "a1" (Grace Hopper, an unrelated seeded agent — see
      // mocks/handlers/agents.ts) rather than "a-self" (MOCK_USER's own
      // agent profile), with conversations.transfer removed, so neither
      // half of the ownership-or-override check is satisfied.
      server.use(
        http.get(`${API_BASE_URL}/auth/me`, () =>
          HttpResponse.json({
            ...MOCK_USER,
            permissions: MOCK_USER.permissions.filter((code) => code !== 'conversations.transfer'),
          }),
        ),
        http.get(`${API_BASE_URL}/conversations/:conversationId`, () =>
          HttpResponse.json({
            id: 'conv-1',
            customer_id: MOCK_CUSTOMER.id,
            channel_config_id: 'c1',
            external_thread_id: 'ext-thread-1',
            status: 'open',
            priority: 'normal',
            queue_id: 'q1',
            assigned_agent_id: 'a1',
            department_id: null,
            last_message_at: '2026-01-01T00:05:00Z',
            first_response_at: null,
            sla_first_response_breached_at: null,
            sla_resolution_breached_at: null,
            sla_first_response_warned_at: null,
            sla_resolution_warned_at: null,
            queue_entered_at: '2026-01-01T00:00:00Z',
            picked_up_at: '2026-01-02T00:00:00Z',
            closed_at: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            autopilot_active: false,
            unread_count: 0,
          } satisfies Conversation),
        ),
      )
      queryClient.clear()
      renderConversationView()
      await openDetails()

      expect(await screen.findByText('Grace Hopper')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /^release$/i })).not.toBeInTheDocument()
    })

    it('a 409 conflict shows an error and immediately refetches the conversation', async () => {
      const user = userEvent.setup()
      renderConversationView()
      await openDetails()

      await pickTheConversation()
      const releaseButton = await screen.findByRole('button', { name: /^release$/i })

      server.use(
        http.post(`${API_BASE_URL}/conversations/:conversationId/release`, () =>
          HttpResponse.json(
            { detail: 'Conversation was already transferred elsewhere.' },
            { status: 409 },
          ),
        ),
        // Only reachable if the 409 handler forces an immediate refetch of
        // the conversation detail query — useConversationQuery has no
        // polling interval of its own, so without that forced refetch this
        // response would never be fetched and the test below would time
        // out rather than pass.
        http.get(`${API_BASE_URL}/conversations/:conversationId`, () =>
          HttpResponse.json({
            id: 'conv-1',
            customer_id: MOCK_CUSTOMER.id,
            channel_config_id: 'c1',
            external_thread_id: 'ext-thread-1',
            status: 'open',
            priority: 'normal',
            queue_id: 'q1',
            assigned_agent_id: null,
            department_id: null,
            last_message_at: '2026-01-01T00:05:00Z',
            first_response_at: null,
            sla_first_response_breached_at: null,
            sla_resolution_breached_at: null,
            sla_first_response_warned_at: null,
            sla_resolution_warned_at: null,
            queue_entered_at: '2026-01-01T00:00:00Z',
            picked_up_at: null,
            closed_at: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            autopilot_active: false,
            unread_count: 0,
          } satisfies Conversation),
        ),
      )
      await user.click(releaseButton)

      expect(await screen.findByText(/already transferred elsewhere/i)).toBeInTheDocument()
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /^release$/i })).not.toBeInTheDocument(),
      )
    })
  })

  describe('AI features', () => {
    it('drafts a reply suggestion into the composer', async () => {
      const user = userEvent.setup()
      renderConversationView()
      await waitForLoaded()

      await user.click(await screen.findByRole('button', { name: /suggest a reply with ai/i }))

      await waitFor(() =>
        expect(screen.getByPlaceholderText(/write a reply/i)).toHaveValue(MOCK_REPLY_SUGGESTION),
      )
    })

    it('surfaces an error if the reply suggestion request fails', async () => {
      const user = userEvent.setup()
      server.use(
        http.post(`${API_BASE_URL}/ai/conversations/:conversationId/reply-suggestion`, () =>
          HttpResponse.json(
            { detail: 'AI features are not enabled for your company.' },
            { status: 503 },
          ),
        ),
      )
      renderConversationView()
      await waitForLoaded()

      await user.click(await screen.findByRole('button', { name: /suggest a reply with ai/i }))

      expect(await screen.findByText(/ai features are not enabled/i)).toBeInTheDocument()
    })

    it('is hidden without the ai.use permission', async () => {
      server.use(
        http.get(`${API_BASE_URL}/auth/me`, () =>
          HttpResponse.json({
            ...MOCK_USER,
            permissions: MOCK_USER.permissions.filter((code) => code !== 'ai.use'),
          }),
        ),
      )
      renderConversationView()
      await openDetails()

      expect(
        screen.queryByRole('button', { name: /suggest a reply with ai/i }),
      ).not.toBeInTheDocument()
      expect(screen.queryByText('AI Summary')).not.toBeInTheDocument()
    })

    it('generates and displays a conversation summary on demand', async () => {
      const user = userEvent.setup()
      renderConversationView()
      await openDetails()

      expect(screen.queryByText(MOCK_CONVERSATION_SUMMARY)).not.toBeInTheDocument()
      await user.click(await screen.findByRole('button', { name: /generate summary/i }))

      expect(await screen.findByText(MOCK_CONVERSATION_SUMMARY)).toBeInTheDocument()
    })

    it('has no detectable accessibility violations with a summary shown', async () => {
      const user = userEvent.setup()
      const { container } = renderConversationView()
      await openDetails()

      await user.click(await screen.findByRole('button', { name: /generate summary/i }))
      await screen.findByText(MOCK_CONVERSATION_SUMMARY)

      expect(await axe(container)).toHaveNoViolations()
    })
  })
})
