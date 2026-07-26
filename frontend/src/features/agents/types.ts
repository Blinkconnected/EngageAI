export type AgentStatus = 'online' | 'away' | 'offline'

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
