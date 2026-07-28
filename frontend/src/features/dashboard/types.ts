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
  /** Active (open/pending) conversations with nobody assigned yet. */
  unassigned: number
  /** Sum of all four statuses. */
  total: number
  /** Open + pending — conversations still being worked. */
  active: number
  /** Active (open/pending) conversations already past an SLA target —
   * first response, resolution, or both. Live "needs attention now",
   * unlike the SLA report's retrospective, date-ranged breach counts. */
  sla_breached: number
}

/** One agent's current, live workload — matches the backend's
 * `AgentWorkloadResponse`. */
export interface AgentWorkload {
  agent_id: string
  agent_name: string
  open_count: number
  pending_count: number
  total_count: number
}

/** Matches the backend's `LiveQueueDepthResponse`. `assigned_count` and
 * `throughput_24h` are kept for backward compatibility — always exactly
 * `picked_count + active_count` and `resolved_24h + closed_24h`
 * respectively (see `docs/architecture/queues-routing.md`'s "Queue
 * stages" section). */
export interface LiveQueueDepth {
  queue_id: string
  queue_name: string
  department_id: string | null
  department_name: string | null
  open_conversations: number
  waiting_count: number
  assigned_count: number
  /** Assigned, but the agent hasn't sent a first reply yet. */
  picked_count: number
  /** Assigned AND the agent has sent at least one reply. */
  active_count: number
  avg_wait_seconds: number | null
  longest_wait_seconds: number | null
  pickup_avg_seconds_24h: number | null
  abandoned_count_24h: number
  sla_breached_count: number
  throughput_24h: number
  resolved_24h: number
  closed_24h: number
}

/** Matches the backend's `LiveDashboardResponse` (`GET /reports/live-dashboard`). */
export interface LiveDashboard {
  agents: LiveAgentCounts
  conversations: LiveConversationCounts
  queues: LiveQueueDepth[]
  agent_workload: AgentWorkload[]
}
