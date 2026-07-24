export type QueueAssignmentStrategy = 'round_robin' | 'least_load'

/** Matches the backend's `QueueResponse`. */
export interface Queue {
  id: string
  name: string
  description: string | null
  department_id: string | null
  assignment_strategy: QueueAssignmentStrategy
  first_response_target_minutes: number | null
  resolution_target_minutes: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}
