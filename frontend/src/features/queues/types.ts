export type QueueAssignmentStrategy = 'round_robin' | 'least_load' | 'manual'

/**
 * The service that decides this queue's SLA, when one does.
 *
 * Carried so the queue editor can disable the SLA fields *and* say where to
 * go instead — a greyed-out box with no destination is a dead end, and the
 * administrator's next question is always "then where?".
 */
export interface QueueSlaOwner {
  service_id: string
  service_name: string
}

/** Matches the backend's `QueueResponse`. */
export interface Queue {
  id: string
  name: string
  description: string | null
  department_id: string | null
  assignment_strategy: QueueAssignmentStrategy
  first_response_target_minutes: number | null
  resolution_target_minutes: number | null
  // An assigned SlaPolicy (see features/sla/types.ts) takes precedence
  // over the two flat target fields above when set.
  sla_policy_id: string | null
  is_active: boolean
  // AI Autopilot — also requires the company-wide
  // settings.ai.autopilot.enabled switch (see features/company/types.ts).
  autopilot_enabled: boolean
  created_at: string
  updated_at: string
  // `null` means this queue's own SLA fields are still in effect — the
  // ordinary case for a company with no service directory yet. Set means
  // they are read-only and the named service decides; the API refuses a
  // change to them with a 409.
  sla_owned_by_service: QueueSlaOwner | null
}

export interface QueueCreateRequest {
  name: string
  description?: string | null
  department_id?: string | null
  assignment_strategy?: QueueAssignmentStrategy
  first_response_target_minutes?: number | null
  resolution_target_minutes?: number | null
  sla_policy_id?: string | null
  autopilot_enabled?: boolean
}

export interface QueueUpdateRequest {
  name?: string
  description?: string | null
  department_id?: string | null
  assignment_strategy?: QueueAssignmentStrategy
  first_response_target_minutes?: number | null
  resolution_target_minutes?: number | null
  is_active?: boolean
  sla_policy_id?: string | null
  autopilot_enabled?: boolean
}

/** The only two condition keys `RoutingEngine` recognizes (see
 * docs/architecture/queues-routing.md) — deliberately narrow, no nesting. */
export interface RoutingRuleConditions {
  channel_type?: string
  body_contains?: string
}

/** Matches the backend's `RoutingRuleResponse`. */
export interface RoutingRule {
  id: string
  priority: number
  conditions: RoutingRuleConditions
  target_queue_id: string
  is_active: boolean
  created_at: string
}

export interface RoutingRuleCreateRequest {
  priority?: number
  conditions: RoutingRuleConditions
  target_queue_id: string
}

export interface RoutingRuleUpdateRequest {
  priority?: number
  conditions?: RoutingRuleConditions
  target_queue_id?: string
  is_active?: boolean
}

export const QUEUE_ASSIGNMENT_STRATEGIES: { value: QueueAssignmentStrategy; label: string }[] = [
  { value: 'manual', label: 'Manual pickup' },
  { value: 'round_robin', label: 'Round robin' },
  { value: 'least_load', label: 'Least load' },
]
