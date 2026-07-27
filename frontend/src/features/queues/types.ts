export type QueueAssignmentStrategy = 'round_robin' | 'least_load' | 'manual'

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
  created_at: string
  updated_at: string
}

export interface QueueCreateRequest {
  name: string
  description?: string | null
  department_id?: string | null
  assignment_strategy?: QueueAssignmentStrategy
  first_response_target_minutes?: number | null
  resolution_target_minutes?: number | null
  sla_policy_id?: string | null
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
