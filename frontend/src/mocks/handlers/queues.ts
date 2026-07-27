import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  Queue,
  QueueCreateRequest,
  QueueUpdateRequest,
  RoutingRule,
  RoutingRuleCreateRequest,
  RoutingRuleUpdateRequest,
} from '../../features/queues/types'
import type { Page } from '../../shared/api/pagination'

const SEED_QUEUES: Queue[] = [
  {
    id: 'q1',
    name: 'General',
    description: null,
    department_id: null,
    assignment_strategy: 'round_robin',
    first_response_target_minutes: null,
    resolution_target_minutes: null,
    sla_policy_id: null,
    is_active: true,
    autopilot_enabled: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  // A second queue with no conversations routed to it — lets tests prove
  // the Inbox's Queue-filter-mode picker (see InboxPage.tsx) actually
  // threads the selected queue's id through to the request (selecting
  // this one should show nothing, unlike "General" which the seeded
  // conversation belongs to — see mocks/handlers/conversations.ts).
  {
    id: 'q2',
    name: 'VIP',
    description: null,
    department_id: null,
    assignment_strategy: 'round_robin',
    first_response_target_minutes: null,
    resolution_target_minutes: null,
    sla_policy_id: null,
    is_active: true,
    autopilot_enabled: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const SEED_ROUTING_RULES: RoutingRule[] = [
  {
    id: 'r1',
    priority: 10,
    conditions: { channel_type: 'web_chat' },
    target_queue_id: 'q2',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  },
]

let queues: Queue[] = [...SEED_QUEUES]
let routingRules: RoutingRule[] = [...SEED_ROUTING_RULES]
let nextQueueId = 100
let nextRuleId = 100

/** Call from a test's beforeEach/afterEach to undo create/update/delete
 * mutations — see resetDepartmentsMock for the same pattern. */
export function resetQueuesMock() {
  queues = [...SEED_QUEUES]
  routingRules = [...SEED_ROUTING_RULES]
  nextQueueId = 100
  nextRuleId = 100
}

export const queuesHandlers = [
  http.get(`${API_BASE_URL}/queues`, ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '100')
    const start = (page - 1) * pageSize
    const body: Page<Queue> = {
      items: queues.slice(start, start + pageSize),
      total: queues.length,
      page,
      page_size: pageSize,
    }
    return HttpResponse.json(body)
  }),

  http.post(`${API_BASE_URL}/queues`, async ({ request }) => {
    const payload = (await request.json()) as QueueCreateRequest
    const created: Queue = {
      id: `q${nextQueueId}`,
      name: payload.name,
      description: payload.description ?? null,
      department_id: payload.department_id ?? null,
      assignment_strategy: payload.assignment_strategy ?? 'manual',
      first_response_target_minutes: payload.first_response_target_minutes ?? null,
      resolution_target_minutes: payload.resolution_target_minutes ?? null,
      sla_policy_id: payload.sla_policy_id ?? null,
      is_active: true,
      autopilot_enabled: payload.autopilot_enabled ?? false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextQueueId += 1
    queues = [...queues, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/queues/:queueId`, async ({ request, params }) => {
    const payload = (await request.json()) as QueueUpdateRequest
    const index = queues.findIndex((queue) => queue.id === params.queueId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...queues[index], ...payload }
    queues = [...queues.slice(0, index), updated, ...queues.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/queues/:queueId`, ({ params }) => {
    queues = queues.filter((queue) => queue.id !== params.queueId)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${API_BASE_URL}/routing-rules`, () => HttpResponse.json(routingRules)),

  http.post(`${API_BASE_URL}/routing-rules`, async ({ request }) => {
    const payload = (await request.json()) as RoutingRuleCreateRequest
    const created: RoutingRule = {
      id: `r${nextRuleId}`,
      priority: payload.priority ?? 100,
      conditions: payload.conditions,
      target_queue_id: payload.target_queue_id,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
    }
    nextRuleId += 1
    routingRules = [...routingRules, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/routing-rules/:ruleId`, async ({ request, params }) => {
    const payload = (await request.json()) as RoutingRuleUpdateRequest
    const index = routingRules.findIndex((rule) => rule.id === params.ruleId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...routingRules[index], ...payload }
    routingRules = [...routingRules.slice(0, index), updated, ...routingRules.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/routing-rules/:ruleId`, ({ params }) => {
    routingRules = routingRules.filter((rule) => rule.id !== params.ruleId)
    return new HttpResponse(null, { status: 204 })
  }),
]
