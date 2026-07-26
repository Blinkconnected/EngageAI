import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { LiveDashboard } from '../../features/dashboard/types'

export const MOCK_LIVE_DASHBOARD: LiveDashboard = {
  agents: { online: 3, away: 1, busy: 2, offline: 2 },
  conversations: { open: 12, pending: 4, resolved: 30, closed: 55 },
  queues: [
    {
      queue_id: 'q1',
      queue_name: 'General',
      department_id: 'd1',
      department_name: 'Support',
      open_conversations: 7,
      waiting_count: 3,
      assigned_count: 4,
      avg_wait_seconds: 125,
      longest_wait_seconds: 340,
      pickup_avg_seconds_24h: 90,
      abandoned_count_24h: 1,
      sla_breached_count: 2,
      throughput_24h: 18,
    },
    {
      queue_id: 'q2',
      queue_name: 'VIP',
      department_id: null,
      department_name: null,
      open_conversations: 5,
      waiting_count: 0,
      assigned_count: 5,
      avg_wait_seconds: null,
      longest_wait_seconds: null,
      pickup_avg_seconds_24h: 45,
      abandoned_count_24h: 0,
      sla_breached_count: 0,
      throughput_24h: 9,
    },
  ],
}

export const dashboardHandlers = [
  http.get(`${API_BASE_URL}/reports/live-dashboard`, () => HttpResponse.json(MOCK_LIVE_DASHBOARD)),
]
