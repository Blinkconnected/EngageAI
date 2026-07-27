import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  Holiday,
  HolidayCreateRequest,
  HolidayUpdateRequest,
  SlaPolicy,
  SlaPolicyCreateRequest,
  SlaPolicyUpdateRequest,
  SlaPreview,
  SlaPreviewRequest,
} from '../../features/sla/types'

const SEED_POLICIES: SlaPolicy[] = [
  {
    id: 'policy1',
    name: 'Standard',
    description: 'Default policy for most queues.',
    first_response_target_minutes: 30,
    resolution_target_minutes: 240,
    warning_threshold_percent: 80,
    business_hours_aware: true,
    escalation_rules: [],
    is_active: true,
    assigned_queue_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const SEED_HOLIDAYS: Holiday[] = [
  { id: 'holiday1', name: "New Year's Day", date: '2027-01-01', recurs_annually: true },
]

let policies: SlaPolicy[] = [...SEED_POLICIES]
let holidays: Holiday[] = [...SEED_HOLIDAYS]
let nextPolicyId = 100
let nextHolidayId = 100

export function resetSlaMock() {
  policies = [...SEED_POLICIES]
  holidays = [...SEED_HOLIDAYS]
  nextPolicyId = 100
  nextHolidayId = 100
}

export const slaHandlers = [
  http.get(`${API_BASE_URL}/sla-policies`, () => HttpResponse.json(policies)),

  http.post(`${API_BASE_URL}/sla-policies`, async ({ request }) => {
    const payload = (await request.json()) as SlaPolicyCreateRequest
    if (policies.some((policy) => policy.name === payload.name)) {
      return HttpResponse.json(
        { detail: 'A policy with this name already exists' },
        { status: 409 },
      )
    }
    const created: SlaPolicy = {
      id: `policy${nextPolicyId}`,
      name: payload.name,
      description: payload.description ?? null,
      first_response_target_minutes: payload.first_response_target_minutes ?? null,
      resolution_target_minutes: payload.resolution_target_minutes ?? null,
      warning_threshold_percent: payload.warning_threshold_percent ?? 80,
      business_hours_aware: payload.business_hours_aware ?? true,
      escalation_rules: payload.escalation_rules ?? [],
      is_active: true,
      assigned_queue_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextPolicyId += 1
    policies = [...policies, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get(`${API_BASE_URL}/sla-policies/:policyId`, ({ params }) => {
    const policy = policies.find((item) => item.id === params.policyId)
    if (!policy) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(policy)
  }),

  http.patch(`${API_BASE_URL}/sla-policies/:policyId`, async ({ request, params }) => {
    const payload = (await request.json()) as SlaPolicyUpdateRequest
    const index = policies.findIndex((policy) => policy.id === params.policyId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...policies[index], ...payload }
    policies = [...policies.slice(0, index), updated, ...policies.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/sla-policies/:policyId`, ({ params }) => {
    const policy = policies.find((item) => item.id === params.policyId)
    if (!policy) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    if (policy.assigned_queue_count > 0) {
      return HttpResponse.json({ detail: 'Policy still assigned to queues' }, { status: 400 })
    }
    policies = policies.filter((item) => item.id !== policy.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE_URL}/sla-policies/preview`, async ({ request }) => {
    const payload = (await request.json()) as SlaPreviewRequest
    const policy = policies.find((item) => item.id === payload.policy_id)
    if (!policy) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const start = new Date(payload.starts_at)
    const deadline = (minutes: number | null) =>
      minutes ? new Date(start.getTime() + minutes * 60_000).toISOString() : null
    const warning = (minutes: number | null) =>
      minutes
        ? new Date(
            start.getTime() + minutes * (policy.warning_threshold_percent / 100) * 60_000,
          ).toISOString()
        : null
    const body: SlaPreview = {
      first_response_warning_at: warning(policy.first_response_target_minutes),
      first_response_deadline: deadline(policy.first_response_target_minutes),
      resolution_warning_at: warning(policy.resolution_target_minutes),
      resolution_deadline: deadline(policy.resolution_target_minutes),
    }
    return HttpResponse.json(body)
  }),

  http.get(`${API_BASE_URL}/holidays`, () => HttpResponse.json(holidays)),

  http.post(`${API_BASE_URL}/holidays`, async ({ request }) => {
    const payload = (await request.json()) as HolidayCreateRequest
    if (holidays.some((holiday) => holiday.date === payload.date)) {
      return HttpResponse.json({ detail: 'A holiday on this date already exists' }, { status: 409 })
    }
    const created: Holiday = {
      id: `holiday${nextHolidayId}`,
      name: payload.name,
      date: payload.date,
      recurs_annually: payload.recurs_annually ?? false,
    }
    nextHolidayId += 1
    holidays = [...holidays, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/holidays/:holidayId`, async ({ request, params }) => {
    const payload = (await request.json()) as HolidayUpdateRequest
    const index = holidays.findIndex((holiday) => holiday.id === params.holidayId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...holidays[index], ...payload }
    holidays = [...holidays.slice(0, index), updated, ...holidays.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/holidays/:holidayId`, ({ params }) => {
    holidays = holidays.filter((holiday) => holiday.id !== params.holidayId)
    return new HttpResponse(null, { status: 204 })
  }),
]
