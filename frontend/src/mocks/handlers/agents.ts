import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  Agent,
  AgentCreateRequest,
  AgentUpdateRequest,
  SelfAvailabilityStatus,
} from '../../features/agents/types'
import type { Page } from '../../shared/api/pagination'
import { MOCK_USER } from './auth'

const SEED_AGENTS: Agent[] = [
  {
    id: 'a1',
    user_id: 'u1',
    email: 'grace@example.com',
    full_name: 'Grace Hopper',
    title: 'Senior Agent',
    department_id: 'd1',
    status: 'online',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    // Matches MOCK_USER's id (mocks/handlers/auth.ts) — the logged-in
    // test user also has an agent profile, same as a real Owner who
    // handles conversations personally. Deliberately in no department
    // (department_id: null) so it doesn't shift DepartmentsPage's own
    // "Support" agent-count assertions, and deliberately NOT named after
    // MOCK_USER's own full_name ("Ada Lovelace") — other tests create
    // their own "Ada Lovelace" agent, and a second row with the same
    // name makes findByText('Ada Lovelace') ambiguous.
    id: 'a-self',
    user_id: '11111111-1111-1111-1111-111111111111',
    email: 'owner@example.com',
    full_name: 'Mock Self Agent',
    title: null,
    department_id: null,
    status: 'online',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

let agents: Agent[] = [...SEED_AGENTS]
let nextId = 100

/** Call from a test's beforeEach/afterEach to undo create/update/delete mutations. */
export function resetAgentsMock() {
  agents = [...SEED_AGENTS]
  nextId = 100
}

export const agentsHandlers = [
  http.get(`${API_BASE_URL}/agents`, ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '20')
    const start = (page - 1) * pageSize
    const body: Page<Agent> = {
      items: agents.slice(start, start + pageSize),
      total: agents.length,
      page,
      page_size: pageSize,
    }
    return HttpResponse.json(body)
  }),

  http.post(`${API_BASE_URL}/agents`, async ({ request }) => {
    const payload = (await request.json()) as AgentCreateRequest
    const created: Agent = {
      id: `a${nextId}`,
      user_id: `u${nextId}`,
      email: payload.email,
      full_name: payload.full_name,
      title: payload.title ?? null,
      department_id: payload.department_id ?? null,
      status: 'offline',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextId += 1
    agents = [...agents, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  // Registered before `/agents/:agentId` below for readability — MSW
  // matches by path-segment count, not declaration order, so "me/status"
  // (two segments after /agents) never actually collides with the
  // single-segment `:agentId` pattern regardless of ordering.
  http.patch(`${API_BASE_URL}/agents/me/status`, async ({ request }) => {
    const payload = (await request.json()) as { status: SelfAvailabilityStatus }
    const index = agents.findIndex((agent) => agent.user_id === MOCK_USER.id)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...agents[index], status: payload.status }
    agents = [...agents.slice(0, index), updated, ...agents.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.patch(`${API_BASE_URL}/agents/:agentId`, async ({ request, params }) => {
    const payload = (await request.json()) as AgentUpdateRequest
    const index = agents.findIndex((agent) => agent.id === params.agentId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...agents[index], ...payload }
    agents = [...agents.slice(0, index), updated, ...agents.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/agents/:agentId`, ({ params }) => {
    agents = agents.filter((agent) => agent.id !== params.agentId)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE_URL}/agents/:agentId/password`, ({ params }) => {
    const exists = agents.some((agent) => agent.id === params.agentId)
    if (!exists) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return new HttpResponse(null, { status: 204 })
  }),
]
