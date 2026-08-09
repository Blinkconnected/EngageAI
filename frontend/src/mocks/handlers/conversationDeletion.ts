import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { ConversationDeletionRequest } from '../../features/conversations/deletionApi'
import type { Page } from '../../shared/api/pagination'

/** Mutable so a test can drive the whole request → decision arc through
 * the same endpoints the app uses, rather than stubbing each response. */
let requests: ConversationDeletionRequest[] = []
let nextId = 1

export function resetConversationDeletionMock(): void {
  requests = []
  nextId = 1
}

/** Seeds a request without going through the API — for tests that start
 * from "an administrator opens the queue" rather than from an agent
 * asking. */
export function seedDeletionRequest(
  overrides: Partial<ConversationDeletionRequest> = {},
): ConversationDeletionRequest {
  const request: ConversationDeletionRequest = {
    id: `dr-${nextId++}`,
    conversation_id: 'conv-1',
    customer_name: 'Grace Blake',
    status: 'pending',
    reason: 'The customer asked us to remove their personal data.',
    requested_by_user_id: 'u-agent',
    requested_by_name: 'Ordinary Agent',
    decided_by_user_id: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    created_at: '2026-08-08T09:00:00Z',
    ...overrides,
  }
  requests.push(request)
  return request
}

export const conversationDeletionHandlers = [
  http.get(`${API_BASE_URL}/conversations/:conversationId/deletion-request`, ({ params }) => {
    const pending = requests.find(
      (request) =>
        request.conversation_id === params.conversationId && request.status === 'pending',
    )
    return HttpResponse.json(pending ?? null)
  }),

  http.post(
    `${API_BASE_URL}/conversations/:conversationId/deletion-request`,
    async ({ params, request: httpRequest }) => {
      const body = (await httpRequest.json()) as { reason: string }
      const already = requests.find(
        (request) =>
          request.conversation_id === params.conversationId && request.status === 'pending',
      )
      if (already) {
        return HttpResponse.json(
          { detail: 'Somebody has already asked for this conversation to be deleted.' },
          { status: 409 },
        )
      }
      const created = seedDeletionRequest({
        conversation_id: String(params.conversationId),
        reason: body.reason,
        requested_by_name: 'Mock Self Agent',
      })
      return HttpResponse.json(created, { status: 201 })
    },
  ),

  http.get(`${API_BASE_URL}/conversation-deletion-requests`, ({ request: httpRequest }) => {
    const status = new URL(httpRequest.url).searchParams.get('status')
    const items = status ? requests.filter((entry) => entry.status === status) : requests
    return HttpResponse.json<Page<ConversationDeletionRequest>>({
      items,
      total: items.length,
      page: 1,
      page_size: 25,
    })
  }),

  ...(['approve', 'reject'] as const).map((decision) =>
    http.post(
      `${API_BASE_URL}/conversation-deletion-requests/:requestId/${decision}`,
      async ({ params, request: httpRequest }) => {
        const body = (await httpRequest.json()) as { note: string | null }
        const found = requests.find((entry) => entry.id === params.requestId)
        if (!found) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
        if (found.status !== 'pending') {
          return HttpResponse.json(
            { detail: `This request has already been ${found.status}.` },
            { status: 409 },
          )
        }
        if (decision === 'reject' && !body.note) {
          return HttpResponse.json(
            { detail: 'Say why you are turning this down.' },
            { status: 400 },
          )
        }
        found.status = decision === 'approve' ? 'approved' : 'rejected'
        found.decided_by_name = 'Mock Self Agent'
        found.decided_at = '2026-08-08T10:00:00Z'
        found.decision_note = body.note
        return HttpResponse.json(found)
      },
    ),
  ),
]
