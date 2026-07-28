export interface DateRange {
  date_from: string
  date_to: string
}

export type ExportFormat = 'pdf' | 'xlsx'

/** Matches the backend's `ConversationStatsRowResponse` — one row per (stat_date, channel_type). */
export interface ConversationStatsRow {
  stat_date: string
  channel_type: string
  opened: number
  closed: number
  resolved: number
  first_response_breached: number
  resolution_breached: number
}

/** Matches the backend's `ExecutiveDashboardResponse` (`GET /reports/executive-dashboard`). */
export interface ExecutiveDashboard {
  date_from: string
  date_to: string
  conversations_opened: number
  conversations_closed: number
  conversations_resolved: number
  first_response_breached: number
  resolution_breached: number
  top_channels: ConversationStatsRow[]
  csat_average_rating: number | null
  csat_response_count: number
  ai_calls_total: number
  active_agent_count: number
}

/** Matches the backend's `AgentDashboardResponse` (`GET /reports/agent-dashboard`). */
export interface AgentDashboard {
  agent_id: string
  date_from: string
  date_to: string
  conversations_assigned: number
  conversations_closed: number
  messages_sent: number
}

/** Matches the backend's `AgentPerformanceRowResponse` (`GET /reports/performance`). */
export interface AgentPerformanceRow {
  agent_id: string
  agent_name: string
  conversations_assigned: number
  conversations_closed: number
  messages_sent: number
}

/** Matches the backend's `QueueStatsRowResponse` (`GET /reports/queues`). */
export interface QueueStatsRow {
  queue_id: string
  queue_name: string
  conversations_entered: number
  sla_breached: number
}

/** Matches the backend's `SlaReportResponse` (`GET /reports/sla`). */
export interface SlaReport {
  date_from: string
  date_to: string
  first_response_breached: number
  resolution_breached: number
  conversations_opened: number
  by_queue: QueueStatsRow[]
}

/** Matches the backend's `CsatDailyRowResponse`. */
export interface CsatDailyRow {
  stat_date: string
  response_count: number
  average_rating: number | null
}

/** Matches the backend's `CsatAgentRowResponse`. */
export interface CsatAgentRow {
  agent_id: string
  agent_name: string
  response_count: number
  average_rating: number | null
}

/** Matches the backend's `CsatReportResponse` (`GET /reports/csat`). */
export interface CsatReport {
  date_from: string
  date_to: string
  response_count: number
  average_rating: number | null
  daily_trend: CsatDailyRow[]
  by_agent: CsatAgentRow[]
}

/** Matches the backend's `AiOperationRowResponse` (`GET /reports/ai`). */
export type AiUsageGranularity = 'daily' | 'weekly' | 'monthly'

/** One agent's AI usage over the reported range — matches the backend's
 * `AiAgentUsageRowResponse`. */
export interface AiAgentUsageRow {
  agent_id: string
  agent_name: string
  total_calls: number
  /** Autopilot replies this agent explicitly asked for. */
  autopilot_agent_requests: number
  /** Autopilot replies that fired automatically on this agent's
   * conversations because an SLA target was slipping — AI covering for
   * the agent rather than the agent choosing to use AI. */
  autopilot_sla_triggers: number
}

export interface AiUsageBucket {
  /** First day of the bucket at whatever granularity was requested. */
  bucket_start: string
  calls: number
}

/** Matches the backend's `AiUsageReportResponse` (`GET /reports/ai/usage`). */
export interface AiUsageReport {
  by_operation: AiOperationRow[]
  by_agent: AiAgentUsageRow[]
  trend: AiUsageBucket[]
  total_calls: number
}

export interface AiOperationRow {
  operation: string
  calls: number
}
