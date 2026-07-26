export interface LiveAgentCounts {
  online: number
  away: number
  busy: number
  offline: number
}

export interface LiveConversationCounts {
  open: number
  pending: number
  resolved: number
  closed: number
}

/** Matches the backend's `LiveQueueDepthResponse`. */
export interface LiveQueueDepth {
  queue_id: string
  queue_name: string
  department_id: string | null
  department_name: string | null
  open_conversations: number
  waiting_count: number
  assigned_count: number
  avg_wait_seconds: number | null
  longest_wait_seconds: number | null
  // Not rendered as their own dashboard columns today (this milestone's
  // enrichment covers waiting/avg-wait/longest-wait/SLA-breach only) but
  // kept typed so this interface fully matches the backend response
  // rather than silently dropping fields a future caller might need.
  pickup_avg_seconds_24h: number | null
  abandoned_count_24h: number
  sla_breached_count: number
  throughput_24h: number
}

/** Matches the backend's `LiveDashboardResponse` (`GET /reports/live-dashboard`). */
export interface LiveDashboard {
  agents: LiveAgentCounts
  conversations: LiveConversationCounts
  queues: LiveQueueDepth[]
}
