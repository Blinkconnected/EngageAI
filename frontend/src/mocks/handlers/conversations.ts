import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import { MOCK_CUSTOMER } from './customers'
import type {
  Attachment,
  Conversation,
  ConversationTransfer,
  ConversationTransferRequest,
  ConversationUpdateRequest,
  InternalNote,
  Message,
  SendMessageRequest,
} from '../../features/conversations/types'

// Seeded as already queued and unassigned (queue_id set, assigned_agent_id
// null, queue_entered_at populated) rather than queue-less — this is the
// only conversation the single-conversation mock "database" below ever
// serves, and the Inbox's Queue-filter-mode / Pick-action tests need a
// queued-and-unassigned row to exercise against, same as every other test
// in this file that reads/mutates this same seed.
const SEED_CONVERSATION: Conversation = {
  id: 'conv-1',
  customer_id: MOCK_CUSTOMER.id,
  channel_config_id: 'c1',
  external_thread_id: 'ext-thread-1',
  status: 'waiting',
  priority: 'normal',
  queue_id: 'q1',
  assigned_agent_id: null,
  department_id: null,
  last_message_at: '2026-01-01T00:05:00Z',
  first_response_at: null,
  sla_health: 'healthy',
  customer_name: MOCK_CUSTOMER.full_name,
  state: 'waiting_for_pickup',
  state_text: 'Waiting for pickup',
  owner_kind: 'queue',
  owner_label: 'the Support queue',
  owner_since: '2026-01-01T00:00:00Z',
  last_event: 'Routed to the "Support" queue.',
  last_event_kind: 'queue_selected',
  last_event_at: '2026-01-01T00:00:00Z',
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
    attachments: [],
  },
]

let conversation: Conversation = { ...SEED_CONVERSATION }
let messages: Message[] = [...SEED_MESSAGES]
let attachments: Attachment[] = []
let notes: InternalNote[] = []
let transfers: ConversationTransfer[] = []
let nextMessageId = 100
let nextAttachmentId = 100
let nextNoteId = 100
let nextTransferId = 100

export function resetConversationsMock() {
  conversation = { ...SEED_CONVERSATION }
  messages = [...SEED_MESSAGES]
  attachments = []
  notes = []
  transfers = []
  nextMessageId = 100
  nextAttachmentId = 100
  nextNoteId = 100
  nextTransferId = 100
}

export const conversationsHandlers = [
  // Ahead of /conversations/:conversationId deliberately: MSW matches in
  // order, and the parameterised route would otherwise swallow "workload".
  http.get(`${API_BASE_URL}/conversations/workload`, () =>
    HttpResponse.json({
      active: 3,
      needs_attention: 1,
      waiting_pickup: 1,
      mine: 0,
      ai_working: 0,
      waiting_customer: 1,
      at_risk: 0,
      breached: 0,
      resolved_today: 2,
    }),
  ),
  http.get(`${API_BASE_URL}/conversations`, ({ request }) => {
    const url = new URL(request.url)
    const statusFilter = url.searchParams.get('status_filter')
    const customerIdFilter = url.searchParams.get('customer_id')
    const assignedAgentIdFilter = url.searchParams.get('assigned_agent_id')
    const queueIdFilter = url.searchParams.get('queue_id')
    const priorityFilter = url.searchParams.get('priority')
    const unassignedOnly = url.searchParams.get('unassigned_only') === 'true'
    let items = !statusFilter || statusFilter === conversation.status ? [conversation] : []
    if (customerIdFilter && conversation.customer_id !== customerIdFilter) items = []
    if (assignedAgentIdFilter && conversation.assigned_agent_id !== assignedAgentIdFilter) {
      items = []
    }
    if (queueIdFilter && conversation.queue_id !== queueIdFilter) items = []
    if (priorityFilter && conversation.priority !== priorityFilter) items = []
    if (unassignedOnly && conversation.assigned_agent_id !== null) items = []

    // Work queues are decided by the server, so the mock has to behave like
    // one: a view the seed is not in returns nothing. Ignoring the parameter
    // would make every queue look identical in tests, which is exactly the
    // bug the views exist to prevent.
    const view = url.searchParams.get('view')
    if (view) {
      const seedIsIn: string[] = ['active', 'needs_attention', 'waiting_pickup']
      if (!seedIsIn.includes(view)) items = []
    }
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 20 })
  }),

  http.get(`${API_BASE_URL}/conversations/:conversationId`, () => HttpResponse.json(conversation)),

  http.patch(`${API_BASE_URL}/conversations/:conversationId`, async ({ request }) => {
    const payload = (await request.json()) as ConversationUpdateRequest
    conversation = { ...conversation, ...payload }
    return HttpResponse.json(conversation)
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/pick`, () => {
    // Mirrors the real backend's 409 on a conversation someone else
    // already holds — tests override this handler's response to
    // exercise that path (see InboxPage.test.tsx's 409-conflict case)
    // rather than needing a second conversation in this single-seed mock.
    if (conversation.assigned_agent_id) {
      return HttpResponse.json(
        { detail: 'This conversation has already been picked up by another agent.' },
        { status: 409 },
      )
    }
    conversation = {
      ...conversation,
      assigned_agent_id: 'a-self',
      picked_up_at: '2026-01-02T00:00:00Z',
    }
    return HttpResponse.json(conversation)
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/release`, () => {
    conversation = { ...conversation, assigned_agent_id: null, picked_up_at: null }
    return HttpResponse.json(conversation)
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/transfer`, async ({ request }) => {
    const payload = (await request.json()) as ConversationTransferRequest
    const created: ConversationTransfer = {
      id: `transfer-${nextTransferId}`,
      conversation_id: conversation.id,
      target_type: payload.target_type,
      from_agent_id: conversation.assigned_agent_id,
      to_agent_id: payload.target_type === 'agent' ? (payload.to_agent_id ?? null) : null,
      to_department_id:
        payload.target_type === 'department' ? (payload.to_department_id ?? null) : null,
      to_queue_id: null,
      note: payload.note ?? null,
      transferred_by_user_id: '11111111-1111-1111-1111-111111111111',
      recipient_was_online: true,
      created_at: '2026-01-02T00:00:00Z',
    }
    nextTransferId += 1
    transfers = [created, ...transfers]
    conversation = {
      ...conversation,
      assigned_agent_id: created.to_agent_id,
      department_id: created.to_department_id,
    }
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get(`${API_BASE_URL}/conversations/:conversationId/transfers`, () =>
    HttpResponse.json({ items: transfers, total: transfers.length, page: 1, page_size: 50 }),
  ),

  http.get(`${API_BASE_URL}/conversations/:conversationId/messages`, () => {
    const ordered = [...messages].reverse() // newest-first, matching the real API
    // Mirrors the real backend: fetching messages IS viewing the
    // conversation, so every unread inbound message is marked read —
    // see ConversationService.list_messages. Keeps the mock's
    // unread_count in sync the same way opening a conversation clears
    // its Inbox badge for real.
    messages = messages.map((message) =>
      message.direction === 'inbound' && message.read_status === 'unread'
        ? { ...message, read_status: 'read', read_at: '2026-01-02T00:00:00Z' }
        : message,
    )
    conversation = { ...conversation, unread_count: 0 }
    return HttpResponse.json({
      items: ordered,
      total: ordered.length,
      page: 1,
      page_size: ordered.length || 20,
    })
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/messages`, async ({ request }) => {
    const payload = (await request.json()) as SendMessageRequest
    // A failed send is still a 201 with status: "failed", not an HTTP
    // error — see conversation_service.py's send_reply. This magic body
    // lets tests exercise that path without a real provider.
    const simulateFailure = payload.body === 'TRIGGER_SEND_FAILURE'
    const linkedAttachments = attachments.filter((a) =>
      (payload.attachment_ids ?? []).includes(a.id),
    )
    const created: Message = {
      id: `msg-${nextMessageId}`,
      conversation_id: conversation.id,
      direction: 'outbound',
      message_type: linkedAttachments.length > 0 ? 'media' : 'text',
      status: simulateFailure ? 'failed' : 'sent',
      delivery_status: simulateFailure ? 'not_applicable' : 'delivered',
      read_status: 'unread',
      body: payload.body ?? null,
      external_message_id: simulateFailure ? null : null,
      reply_to_message_id: null,
      message_metadata: simulateFailure ? { error: 'simulated provider send failure' } : {},
      sent_at: simulateFailure ? null : '2026-01-01T00:10:00Z',
      delivered_at: simulateFailure ? null : '2026-01-01T00:10:01Z',
      read_at: null,
      created_at: '2026-01-01T00:10:00Z',
      attachments: linkedAttachments,
    }
    nextMessageId += 1
    messages = [...messages, created]
    attachments = attachments.map((a) =>
      linkedAttachments.some((linked) => linked.id === a.id) ? { ...a, message_id: created.id } : a,
    )
    return HttpResponse.json(created, { status: 201 })
  }),

  http.post(`${API_BASE_URL}/conversations/:conversationId/attachments`, async ({ request }) => {
    const formData = await request.formData()
    const file = formData.get('file') as File | null
    const contentType = file?.type || 'image/png'
    const isImage = contentType.startsWith('image/')
    const created: Attachment = {
      id: `att-${nextAttachmentId}`,
      filename: file?.name ?? 'file.png',
      content_type: contentType,
      size_bytes: file?.size ?? 123,
      validation_status: 'approved',
      message_id: null,
      created_at: '2026-01-01T00:00:00Z',
      // The media fields the API returns. Mirrored here rather than left
      // off, so a component that renders an upload the way it renders a
      // received file is exercised against the same shape.
      kind: isImage ? 'image' : 'file',
      inline: isImage,
      needs_fallback: false,
      width: isImage ? 800 : null,
      height: isImage ? 600 : null,
      media_url: isImage ? `/media/att-${nextAttachmentId}` : null,
    }
    nextAttachmentId += 1
    attachments = [...attachments, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get(
    `${API_BASE_URL}/conversations/:conversationId/attachments/:attachmentId/download`,
    ({ params }) => {
      const attachment = attachments.find((a) => a.id === params.attachmentId)
      return new HttpResponse(new Blob(['fake-file-bytes']), {
        headers: {
          'Content-Type': attachment?.content_type ?? 'application/octet-stream',
          'Content-Disposition': `attachment; filename="${attachment?.filename ?? 'file'}"`,
        },
      })
    },
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
