import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import { MOCK_CUSTOMER } from './customers'
import type {
  Conversation,
  ConversationUpdateRequest,
  InternalNote,
  Message,
  SendMessageRequest,
} from '../../features/conversations/types'

const SEED_CONVERSATION: Conversation = {
  id: 'conv-1',
  customer_id: MOCK_CUSTOMER.id,
  channel_config_id: 'c1',
  external_thread_id: 'ext-thread-1',
  status: 'open',
  queue_id: null,
  assigned_agent_id: null,
  last_message_at: '2026-01-01T00:05:00Z',
  first_response_at: null,
  sla_first_response_breached_at: null,
  sla_resolution_breached_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const SEED_MESSAGES: Message[] = [
  {
    id: 'msg-1',
    conversation_id: 'conv-1',
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
  },
]

let conversation: Conversation = { ...SEED_CONVERSATION }
let messages: Message[] = [...SEED_MESSAGES]
let notes: InternalNote[] = []
let nextMessageId = 100
let nextNoteId = 100

export function resetConversationsMock() {
  conversation = { ...SEED_CONVERSATION }
  messages = [...SEED_MESSAGES]
  notes = []
  nextMessageId = 100
  nextNoteId = 100
}

export const conversationsHandlers = [
  http.get(`${API_BASE_URL}/conversations`, ({ request }) => {
    const url = new URL(request.url)
    const statusFilter = url.searchParams.get('status_filter')
    const customerIdFilter = url.searchParams.get('customer_id')
    let items = !statusFilter || statusFilter === conversation.status ? [conversation] : []
    if (customerIdFilter && conversation.customer_id !== customerIdFilter) items = []
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 20 })
  }),

  http.get(`${API_BASE_URL}/conversations/:conversationId`, () => HttpResponse.json(conversation)),

  http.patch(`${API_BASE_URL}/conversations/:conversationId`, async ({ request }) => {
    const payload = (await request.json()) as ConversationUpdateRequest
    conversation = { ...conversation, ...payload }
    return HttpResponse.json(conversation)
  }),

  http.get(`${API_BASE_URL}/conversations/:conversationId/messages`, () => {
    const ordered = [...messages].reverse() // newest-first, matching the real API
    return HttpResponse.json({
      items: ordered,
      total: ordered.length,
      page: 1,
      page_size: ordered.length || 20,
    })
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/messages`, async ({ request }) => {
    const payload = (await request.json()) as SendMessageRequest
    const created: Message = {
      id: `msg-${nextMessageId}`,
      conversation_id: conversation.id,
      direction: 'outbound',
      message_type: 'text',
      status: 'sent',
      delivery_status: 'delivered',
      read_status: 'unread',
      body: payload.body ?? null,
      external_message_id: null,
      reply_to_message_id: null,
      message_metadata: {},
      sent_at: '2026-01-01T00:10:00Z',
      delivered_at: '2026-01-01T00:10:01Z',
      read_at: null,
      created_at: '2026-01-01T00:10:00Z',
    }
    nextMessageId += 1
    messages = [...messages, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/attachments`, () =>
    HttpResponse.json(
      {
        id: 'att-1',
        filename: 'file.png',
        content_type: 'image/png',
        size_bytes: 123,
        validation_status: 'approved',
        message_id: null,
        created_at: '2026-01-01T00:00:00Z',
      },
      { status: 201 },
    ),
  ),

  http.get(`${API_BASE_URL}/conversations/:conversationId/notes`, () =>
    HttpResponse.json({ items: notes, total: notes.length, page: 1, page_size: 50 }),
  ),

  http.post(`${API_BASE_URL}/conversations/:conversationId/notes`, async ({ request }) => {
    const payload = (await request.json()) as { body: string }
    const created: InternalNote = {
      id: `note-${nextNoteId}`,
      conversation_id: conversation.id,
      author_user_id: null,
      body: payload.body,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextNoteId += 1
    notes = [...notes, created]
    return HttpResponse.json(created, { status: 201 })
  }),
]
