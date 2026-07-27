import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  CsatContactInfoRequest,
  CsatContactInfoResponse,
  CsatContext,
  CsatSubmitRequest,
  CsatSubmitResponse,
} from '../../features/feedback/types'

const SEED_CONTEXTS: Record<string, CsatContext> = {
  conv1: { conversation_id: 'conv1', already_responded: false, needs_contact_info: true },
  conv2: { conversation_id: 'conv2', already_responded: false, needs_contact_info: false },
}

const SEED_CUSTOMER_CONTACT: Record<string, { email: string | null; phone: string | null }> = {
  conv1: { email: null, phone: null },
  conv2: { email: 'existing@example.com', phone: null },
}

let contexts: Record<string, CsatContext> = { ...SEED_CONTEXTS }
let customerContact: Record<string, { email: string | null; phone: string | null }> = {
  ...SEED_CUSTOMER_CONTACT,
}

export function resetCsatMock() {
  contexts = { ...SEED_CONTEXTS }
  customerContact = { ...SEED_CUSTOMER_CONTACT }
}

export const csatHandlers = [
  http.get(`${API_BASE_URL}/csat/:conversationId`, ({ params, request }) => {
    const token = new URL(request.url).searchParams.get('token')
    if (token === 'invalid-token') {
      return HttpResponse.json(
        { detail: 'CSAT survey link is invalid or expired' },
        { status: 401 },
      )
    }
    const conversationId = params.conversationId as string
    const context = contexts[conversationId]
    if (!context) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(context)
  }),

  http.post(`${API_BASE_URL}/csat/:conversationId/contact-info`, async ({ params, request }) => {
    const conversationId = params.conversationId as string
    const payload = (await request.json()) as CsatContactInfoRequest
    const current = customerContact[conversationId] ?? { email: null, phone: null }
    const updated = {
      email: current.email ?? payload.email ?? null,
      phone: current.phone ?? payload.phone ?? null,
    }
    customerContact[conversationId] = updated
    if (contexts[conversationId]) {
      contexts[conversationId] = { ...contexts[conversationId], needs_contact_info: false }
    }
    const body: CsatContactInfoResponse = { conversation_id: conversationId, ...updated }
    return HttpResponse.json(body)
  }),

  http.post(`${API_BASE_URL}/csat/:conversationId/respond`, async ({ params, request }) => {
    const conversationId = params.conversationId as string
    const payload = (await request.json()) as CsatSubmitRequest
    if (contexts[conversationId]) {
      contexts[conversationId] = { ...contexts[conversationId], already_responded: true }
    }
    const body: CsatSubmitResponse = {
      conversation_id: conversationId,
      rating: payload.rating,
      comment: payload.comment ?? null,
    }
    return HttpResponse.json(body)
  }),
]
