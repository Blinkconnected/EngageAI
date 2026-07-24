import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Department } from '../../features/departments/types'
import type { Page } from '../../shared/api/pagination'

export const MOCK_DEPARTMENTS: Department[] = [
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

export const departmentsHandlers = [
  http.get(`${API_BASE_URL}/departments`, () => {
    const page: Page<Department> = {
      items: MOCK_DEPARTMENTS,
      total: MOCK_DEPARTMENTS.length,
      page: 1,
      page_size: 100,
    }
    return HttpResponse.json(page)
  }),
]
