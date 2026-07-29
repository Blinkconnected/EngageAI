import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { resetConversationsMock } from '../../mocks/handlers/conversations'
import { ConversationViewPage } from './ConversationViewPage'

function renderConversation() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationViewPage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

/** Every assertion in this file is about controls that live in the
 * customer-details panel, which is now opened on demand from the
 * conversation's ⋮ menu rather than being a permanent column — so
 * "loaded" here means "details open and populated". */
/** Page-ready without opening anything — for the reply-composer tests
 * below, which sit *behind* the details overlay and can't be typed into
 * while it's open. */
async function waitForComposer() {
  return screen.findByRole('tab', { name: /messages/i })
}

async function waitForLoaded() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /conversation actions/i }))
  await user.click(await screen.findByRole('menuitem', { name: /conversation details/i }))
  return screen.findByLabelText(/^status/i)
}

/** A conversation Autopilot holds *and* that is still assigned — the
 * shape the "on agent request" mode produces, which `pick` cannot
 * resolve. */
const CONV_ASSIGNED_AUTOPILOT = {
          id: 'conv-1',
          customer_id: '33333333-3333-3333-3333-333333333333',
          channel_config_id: 'c1',
          external_thread_id: 'ext-thread-1',
          status: 'open',
          priority: 'normal',
          queue_id: 'q1',
          assigned_agent_id: 'a-self',
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
          autopilot_active: true,
          unread_count: 0,
        }

describe('AI Autopilot — On Agent Request', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetConversationsMock()
  })

  it('offers an "Ask AI to reply" action on a conversation a human still holds', async () => {
    renderConversation()
    await waitForLoaded()

    expect(await screen.findByRole('button', { name: /ask ai to reply/i })).toBeInTheDocument()
  })

  it('hands the conversation to Autopilot, and reflects that it took over', async () => {
    const user = userEvent.setup()
    let requested = false
    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/autopilot`, () => {
        requested = true
        return HttpResponse.json({
          id: 'conv-1',
          customer_id: '33333333-3333-3333-3333-333333333333',
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
          autopilot_active: true,
          unread_count: 0,
        })
      }),
    )
    renderConversation()
    await waitForLoaded()

    await user.click(await screen.findByRole('button', { name: /ask ai to reply/i }))

    await waitFor(() => expect(requested).toBe(true))
    // Once Autopilot owns the conversation the request action goes away —
    // it is already replying, and the relevant action becomes taking it
    // back (Pick up).
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /ask ai to reply/i })).not.toBeInTheDocument(),
    )
    expect(await screen.findByText(/ai autopilot/i)).toBeInTheDocument()
  })

  it('surfaces the 409 an administrator sees when the agent-request mode is turned off', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/autopilot`, () =>
        HttpResponse.json(
          {
            detail:
              "AI Autopilot's 'on agent request' mode is turned off for this company. " +
              'An administrator can enable it in Settings → AI.',
          },
          { status: 409 },
        ),
      ),
    )
    renderConversation()
    await waitForLoaded()

    await user.click(await screen.findByRole('button', { name: /ask ai to reply/i }))

    expect(await screen.findByText(/on agent request.*turned off/i)).toBeInTheDocument()
  })
})

describe('Taking a conversation back from AI Autopilot', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetConversationsMock()
  })

  it('offers a takeover button while Autopilot holds the conversation, even though it is assigned', async () => {
    // The agent-request case: the requesting agent keeps the assignment,
    // so "Pick up" has nothing to claim and stays hidden — this button is
    // their only route back.
    server.use(
      http.get(`${API_BASE_URL}/conversations/:conversationId`, () =>
        HttpResponse.json(CONV_ASSIGNED_AUTOPILOT),
      ),
    )
    renderConversation()
    await waitForLoaded()

    expect(await screen.findByRole('button', { name: /take over from ai/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^pick up$/i })).not.toBeInTheDocument()
  })

  it('stops Autopilot and returns the conversation to the agent', async () => {
    const user = userEvent.setup()
    let stopped = false
    server.use(
      http.get(`${API_BASE_URL}/conversations/:conversationId`, () =>
        HttpResponse.json(CONV_ASSIGNED_AUTOPILOT),
      ),
      http.delete(`${API_BASE_URL}/conversations/:conversationId/autopilot`, () => {
        stopped = true
        return HttpResponse.json({ ...CONV_ASSIGNED_AUTOPILOT, autopilot_active: false })
      }),
    )
    renderConversation()
    await waitForLoaded()

    await user.click(await screen.findByRole('button', { name: /take over from ai/i }))

    await waitFor(() => expect(stopped).toBe(true))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /take over from ai/i })).not.toBeInTheDocument(),
    )
    // Back under human control, so handing it to AI is on offer again.
    expect(await screen.findByRole('button', { name: /ask ai to reply/i })).toBeInTheDocument()
  })

  it('does not offer a takeover on a conversation Autopilot does not hold', async () => {
    renderConversation()
    await waitForLoaded()
    await screen.findByRole('button', { name: /ask ai to reply/i })

    expect(screen.queryByRole('button', { name: /take over from ai/i })).not.toBeInTheDocument()
  })
})

describe('AI-assisted composer', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetConversationsMock()
  })

  it('reports a hand-typed reply as NOT AI-assisted', async () => {
    const user = userEvent.setup()
    const sent: { isAiAssisted?: boolean } = {}
    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/messages`, async ({ request }) => {
        const body = (await request.json()) as { is_ai_assisted?: boolean }
        sent.isAiAssisted = body.is_ai_assisted
        return HttpResponse.json(
          {
            id: 'msg-new',
            conversation_id: 'conv-1',
            direction: 'outbound',
            message_type: 'text',
            status: 'sent',
            delivery_status: 'delivered',
            read_status: 'unread',
            body: 'Typed by hand',
            external_message_id: null,
            reply_to_message_id: null,
            message_metadata: {},
            sent_at: '2026-01-01T00:10:00Z',
            delivered_at: null,
            read_at: null,
            created_at: '2026-01-01T00:10:00Z',
            attachments: [],
          },
          { status: 201 },
        )
      }),
    )
    renderConversation()
    await waitForComposer()

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'Typed by hand')
    await user.click(screen.getByLabelText(/send reply/i))

    await waitFor(() => expect(sent.isAiAssisted).toBe(false))
  })

  it('reports a reply seeded by "Suggest reply" as AI-assisted, even after the agent edits it', async () => {
    const user = userEvent.setup()
    const sent: { isAiAssisted?: boolean } = {}
    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/messages`, async ({ request }) => {
        const body = (await request.json()) as { is_ai_assisted?: boolean }
        sent.isAiAssisted = body.is_ai_assisted
        return HttpResponse.json(
          {
            id: 'msg-new',
            conversation_id: 'conv-1',
            direction: 'outbound',
            message_type: 'text',
            status: 'sent',
            delivery_status: 'delivered',
            read_status: 'unread',
            body: 'edited',
            external_message_id: null,
            reply_to_message_id: null,
            message_metadata: {},
            sent_at: '2026-01-01T00:10:00Z',
            delivered_at: null,
            read_at: null,
            created_at: '2026-01-01T00:10:00Z',
            attachments: [],
          },
          { status: 201 },
        )
      }),
    )
    renderConversation()
    await waitForComposer()

    await user.click(await screen.findByRole('button', { name: /suggest a reply with ai/i }))
    const box = screen.getByPlaceholderText(/write a reply/i)
    await waitFor(() => expect(box).not.toHaveValue(''))
    // Editing an AI draft keeps it AI-assisted — the flag measures AI's
    // contribution, not verbatim sending.
    await user.type(box, ' — and a human tweak')
    await user.click(screen.getByLabelText(/send reply/i))

    await waitFor(() => expect(sent.isAiAssisted).toBe(true))
  })

  it('stops reporting AI assistance once the agent clears the AI draft entirely', async () => {
    const user = userEvent.setup()
    const sent: { isAiAssisted?: boolean } = {}
    server.use(
      http.post(`${API_BASE_URL}/conversations/:conversationId/messages`, async ({ request }) => {
        const body = (await request.json()) as { is_ai_assisted?: boolean }
        sent.isAiAssisted = body.is_ai_assisted
        return HttpResponse.json(
          {
            id: 'msg-new',
            conversation_id: 'conv-1',
            direction: 'outbound',
            message_type: 'text',
            status: 'sent',
            delivery_status: 'delivered',
            read_status: 'unread',
            body: 'all mine',
            external_message_id: null,
            reply_to_message_id: null,
            message_metadata: {},
            sent_at: '2026-01-01T00:10:00Z',
            delivered_at: null,
            read_at: null,
            created_at: '2026-01-01T00:10:00Z',
            attachments: [],
          },
          { status: 201 },
        )
      }),
    )
    renderConversation()
    await waitForComposer()

    await user.click(await screen.findByRole('button', { name: /suggest a reply with ai/i }))
    const box = screen.getByPlaceholderText(/write a reply/i)
    await waitFor(() => expect(box).not.toHaveValue(''))
    await user.clear(box)
    await user.type(box, 'all mine')
    await user.click(screen.getByLabelText(/send reply/i))

    await waitFor(() => expect(sent.isAiAssisted).toBe(false))
  })
})

describe('AI provenance indicators in the thread', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetConversationsMock()
  })

  it('marks a reply Autopilot sent unattended, and leaves a manual reply unmarked', async () => {
    server.use(
      http.get(`${API_BASE_URL}/conversations/:conversationId/messages`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'msg-ai',
              conversation_id: 'conv-1',
              direction: 'outbound',
              message_type: 'text',
              status: 'sent',
              delivery_status: 'delivered',
              read_status: 'read',
              body: 'Autopilot answered this one.',
              external_message_id: null,
              reply_to_message_id: null,
              message_metadata: { is_ai_generated: true },
              sent_at: '2026-01-01T00:09:00Z',
              delivered_at: null,
              read_at: null,
              created_at: '2026-01-01T00:09:00Z',
              attachments: [],
            },
            {
              id: 'msg-human',
              conversation_id: 'conv-1',
              direction: 'outbound',
              message_type: 'text',
              status: 'sent',
              delivery_status: 'delivered',
              read_status: 'read',
              body: 'A human wrote this one.',
              external_message_id: null,
              reply_to_message_id: null,
              message_metadata: {},
              sent_at: '2026-01-01T00:08:00Z',
              delivered_at: null,
              read_at: null,
              created_at: '2026-01-01T00:08:00Z',
              attachments: [],
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        }),
      ),
    )
    renderConversation()
    await waitForLoaded()

    const aiBubble = (await screen.findByText('Autopilot answered this one.')).closest(
      '.MuiPaper-root',
    ) as HTMLElement
    expect(within(aiBubble).getByText('AI')).toBeInTheDocument()

    const humanBubble = screen.getByText('A human wrote this one.').closest(
      '.MuiPaper-root',
    ) as HTMLElement
    expect(within(humanBubble).queryByText('AI')).not.toBeInTheDocument()
  })
})
