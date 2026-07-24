import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Queue } from '../../features/queues/types'

export const MOCK_QUEUES: Queue[] = [
  {
    id: 'q1',
    name: 'General',
    description: null,
    department_id: null,
    assignment_strategy: 'round_robin',
    first_response_target_minutes: null,
    resolution_target_minutes: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

export const queuesHandlers = [
  http.get(`${API_BASE_URL}/queues`, () =>
    HttpResponse.json({ items: MOCK_QUEUES, total: MOCK_QUEUES.length, page: 1, page_size: 100 }),
  ),
]
