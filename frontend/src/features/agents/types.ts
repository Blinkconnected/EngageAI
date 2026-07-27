export type AgentStatus = 'online' | 'away' | 'busy' | 'offline'

/** Statuses an agent can set for themselves via `PATCH /agents/me/status`
 * — excludes `offline`, which stays connection-derived only. */
export type SelfAvailabilityStatus = 'online' | 'away' | 'busy'

/** Matches the backend's `AgentResponse`. */
export interface Agent {
  id: string
  user_id: string
  email: string
  full_name: string
  title: string | null
  department_id: string | null
  status: AgentStatus
  created_at: string
  updated_at: string
}

export interface AgentCreateRequest {
  email: string
  full_name: string
  /** Omit to invite the agent by email instead — a random password is
   * generated and emailed to them (see AgentCreateDialog vs. the
   * Company Onboarding Wizard's Team Setup step, which omits this). */
  password?: string
  title?: string | null
  department_id?: string | null
}

export interface AgentUpdateRequest {
  title?: string | null
  department_id?: string | null
  status?: AgentStatus
}

/** Body for `POST /agents/{id}/removal` — see AgentRemovalDialog.tsx.
 * `transfer_to_agent_id` is required (and validated server-side) only
 * when `mode` is `'transfer'`. */
export interface AgentRemovalRequest {
  mode: 'transfer' | 'permanent'
  transfer_to_agent_id?: string
}
