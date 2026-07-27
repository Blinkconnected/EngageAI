import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { LiveDashboard } from '../../features/dashboard/types'

export const MOCK_LIVE_DASHBOARD: LiveDashboard = {
  agents: { online: 3, away: 1, busy: 2, offline: 2 },
  conversations: {
    open: 12,
    pending: 4,
    resolved: 30,
    closed: 55,
    unassigned: 3,
    total: 101,
    active: 16,
  },
  agent_workload: [
    { agent_id: 'a1', agent_name: 'Grace Blake', open_count: 5, pending_count: 1, total_count: 6 },
    { agent_id: 'a2', agent_name: 'Sam Ortiz', open_count: 2, pending_count: 2, total_count: 4 },
    { agent_id: 'a3', agent_name: 'Priya Nair', open_count: 0, pending_count: 0, total_count: 0 },
  ],
  queues: [
    {
      queue_id: 'q1',
      queue_name: 'General',
      department_id: 'd1',
      department_name: 'Support',
      open_conversations: 7,
      waiting_count: 3,
      assigned_count: 4,
      picked_count: 1,
      active_count: 3,
      avg_wait_seconds: 125,
      longest_wait_seconds: 340,
      pickup_avg_seconds_24h: 90,
      abandoned_count_24h: 1,
      sla_breached_count: 2,
      throughput_24h: 18,
      resolved_24h: 10,
      closed_24h: 8,
    },
    {
      queue_id: 'q2',
      queue_name: 'VIP',
      department_id: null,
      department_name: null,
      open_conversations: 5,
      waiting_count: 0,
      assigned_count: 5,
      picked_count: 2,
      active_count: 3,
      avg_wait_seconds: null,
      longest_wait_seconds: null,
      pickup_avg_seconds_24h: 45,
      abandoned_count_24h: 0,
      sla_breached_count: 0,
      throughput_24h: 9,
      resolved_24h: 6,
      closed_24h: 3,
    },
  ],
}

export const dashboardHandlers = [
  http.get(`${API_BASE_URL}/reports/live-dashboard`, () => HttpResponse.json(MOCK_LIVE_DASHBOARD)),
]
