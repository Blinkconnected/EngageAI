export interface LiveAgentCounts {
  online: number
  away: number
  offline: number
}

export interface LiveConversationCounts {
  open: number
  pending: number
  resolved: number
  closed: number
}

export interface LiveQueueDepth {
  queue_id: string
  queue_name: string
  open_conversations: number
}

/** Matches the backend's `LiveDashboardResponse` (`GET /reports/live-dashboard`). */
export interface LiveDashboard {
  agents: LiveAgentCounts
  conversations: LiveConversationCounts
  queues: LiveQueueDepth[]
}
