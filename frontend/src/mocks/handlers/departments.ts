import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  Department,
  DepartmentCreateRequest,
  DepartmentUpdateRequest,
} from '../../features/departments/types'
import type { Page } from '../../shared/api/pagination'

const SEED_DEPARTMENTS: Department[] = [
  {
    id: 'd1',
    name: 'Support',
    description: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'd2',
    name: 'Sales',
    description: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

let departments: Department[] = [...SEED_DEPARTMENTS]
let nextId = 100

/** Call from a test's beforeEach/afterEach to undo create/update/delete mutations. */
export function resetDepartmentsMock() {
  departments = [...SEED_DEPARTMENTS]
  nextId = 100
}

export const departmentsHandlers = [
  http.get(`${API_BASE_URL}/departments`, ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '20')
    const start = (page - 1) * pageSize
    const body: Page<Department> = {
      items: departments.slice(start, start + pageSize),
      total: departments.length,
      page,
      page_size: pageSize,
    }
    return HttpResponse.json(body)
  }),

  http.post(`${API_BASE_URL}/departments`, async ({ request }) => {
    const payload = (await request.json()) as DepartmentCreateRequest
    const created: Department = {
      id: `d${nextId}`,
      name: payload.name,
      description: payload.description ?? null,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextId += 1
    departments = [...departments, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/departments/:departmentId`, async ({ request, params }) => {
    const payload = (await request.json()) as DepartmentUpdateRequest
    const index = departments.findIndex((department) => department.id === params.departmentId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const updated = { ...departments[index], ...payload }
    departments = [...departments.slice(0, index), updated, ...departments.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/departments/:departmentId`, ({ params }) => {
    departments = departments.filter((department) => department.id !== params.departmentId)
    return new HttpResponse(null, { status: 204 })
  }),
]
