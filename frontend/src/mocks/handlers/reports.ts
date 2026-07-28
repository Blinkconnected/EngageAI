import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  AgentDashboard,
  AgentPerformanceRow,
  AiOperationRow,
  AiUsageReport,
  ConversationStatsRow,
  CsatReport,
  ExecutiveDashboard,
  QueueStatsRow,
  SlaReport,
} from '../../features/reports/types'

export const MOCK_CONVERSATION_STATS: ConversationStatsRow[] = [
  {
    stat_date: '2026-07-01',
    channel_type: 'whatsapp',
    opened: 8,
    closed: 6,
    resolved: 5,
    first_response_breached: 1,
    resolution_breached: 0,
  },
  {
    stat_date: '2026-07-01',
    channel_type: 'web_chat',
    opened: 4,
    closed: 3,
    resolved: 3,
    first_response_breached: 0,
    resolution_breached: 0,
  },
]

export const MOCK_EXECUTIVE_DASHBOARD: ExecutiveDashboard = {
  date_from: '2026-07-01',
  date_to: '2026-07-24',
  conversations_opened: 42,
  conversations_closed: 30,
  conversations_resolved: 28,
  first_response_breached: 3,
  resolution_breached: 1,
  top_channels: MOCK_CONVERSATION_STATS,
  csat_average_rating: 4.5,
  csat_response_count: 12,
  ai_calls_total: 20,
  active_agent_count: 4,
}

export const MOCK_AGENT_DASHBOARD: AgentDashboard = {
  agent_id: 'agent-1',
  date_from: '2026-07-01',
  date_to: '2026-07-24',
  conversations_assigned: 10,
  conversations_closed: 8,
  messages_sent: 45,
}

export const MOCK_PERFORMANCE_ROWS: AgentPerformanceRow[] = [
  {
    agent_id: 'agent-1',
    agent_name: 'Alex Agent',
    conversations_assigned: 10,
    conversations_closed: 8,
    messages_sent: 45,
  },
  {
    agent_id: 'agent-2',
    agent_name: 'Jamie Rivera',
    conversations_assigned: 6,
    conversations_closed: 4,
    messages_sent: 22,
  },
]

export const MOCK_QUEUE_ROWS: QueueStatsRow[] = [
  { queue_id: 'queue-1', queue_name: 'General', conversations_entered: 20, sla_breached: 2 },
  { queue_id: 'queue-2', queue_name: 'VIP', conversations_entered: 8, sla_breached: 0 },
]

export const MOCK_SLA_REPORT: SlaReport = {
  date_from: '2026-07-01',
  date_to: '2026-07-24',
  first_response_breached: 3,
  resolution_breached: 1,
  conversations_opened: 42,
  by_queue: MOCK_QUEUE_ROWS,
}

export const MOCK_CSAT_REPORT: CsatReport = {
  date_from: '2026-07-01',
  date_to: '2026-07-24',
  response_count: 12,
  average_rating: 4.5,
  daily_trend: [
    { stat_date: '2026-07-01', response_count: 3, average_rating: 4.7 },
    { stat_date: '2026-07-02', response_count: 2, average_rating: 4.3 },
  ],
  by_agent: [
    { agent_id: 'agent-1', agent_name: 'Alex Agent', response_count: 7, average_rating: 4.6 },
    { agent_id: 'agent-2', agent_name: 'Jamie Rivera', response_count: 5, average_rating: 4.3 },
  ],
}

export const MOCK_AI_ROWS: AiOperationRow[] = [
  { operation: 'suggest_reply', calls: 12 },
  { operation: 'summarize_conversation', calls: 5 },
  { operation: 'translate', calls: 3 },
]

function isExportRequest(request: Request): boolean {
  return new URL(request.url).searchParams.get('export') != null
}

function exportResponse() {
  return new HttpResponse(new Blob(['mock-export-bytes']), {
    headers: {
      'content-type': 'application/octet-stream',
      'content-disposition': 'attachment; filename="report.bin"',
    },
  })
}

export const MOCK_AI_USAGE_REPORT: AiUsageReport = {
  by_operation: MOCK_AI_ROWS,
  by_agent: [
    {
      agent_id: 'a1',
      agent_name: 'Grace Blake',
      total_calls: 9,
      autopilot_agent_requests: 3,
      autopilot_sla_triggers: 1,
    },
  ],
  trend: [
    { bucket_start: '2026-01-01', calls: 4 },
    { bucket_start: '2026-01-02', calls: 5 },
  ],
  total_calls: 9,
}

export const reportsHandlers = [
  http.get(`${API_BASE_URL}/reports/executive-dashboard`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_EXECUTIVE_DASHBOARD),
  ),
  http.get(`${API_BASE_URL}/reports/agent-dashboard`, () =>
    HttpResponse.json(MOCK_AGENT_DASHBOARD),
  ),
  http.get(`${API_BASE_URL}/reports/conversations`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_CONVERSATION_STATS),
  ),
  http.get(`${API_BASE_URL}/reports/performance`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_PERFORMANCE_ROWS),
  ),
  http.get(`${API_BASE_URL}/reports/queues`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_QUEUE_ROWS),
  ),
  http.get(`${API_BASE_URL}/reports/sla`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_SLA_REPORT),
  ),
  http.get(`${API_BASE_URL}/reports/csat`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_CSAT_REPORT),
  ),
  http.get(`${API_BASE_URL}/reports/ai/usage`, () => HttpResponse.json(MOCK_AI_USAGE_REPORT)),
  http.get(`${API_BASE_URL}/reports/ai`, ({ request }) =>
    isExportRequest(request) ? exportResponse() : HttpResponse.json(MOCK_AI_ROWS),
  ),
]
