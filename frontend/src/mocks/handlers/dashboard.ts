import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { LiveDashboard } from '../../features/dashboard/types'

export const MOCK_LIVE_DASHBOARD: LiveDashboard = {
  agents: { online: 3, away: 1, offline: 2 },
  conversations: { open: 12, pending: 4, resolved: 30, closed: 55 },
  queues: [
    { queue_id: 'q1', queue_name: 'General', open_conversations: 7 },
    { queue_id: 'q2', queue_name: 'VIP', open_conversations: 5 },
  ],
}

export const dashboardHandlers = [
  http.get(`${API_BASE_URL}/reports/live-dashboard`, () => HttpResponse.json(MOCK_LIVE_DASHBOARD)),
]
