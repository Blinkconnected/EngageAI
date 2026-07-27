export type EscalationTrigger = 'warning' | 'breach'
export type EscalationAction = 'reassign_queue' | 'reassign_agent' | 'notify'

/** Matches the backend's `EscalationRule` (api.schemas.sla) — which
 * extra field is required depends on `action`. */
export interface EscalationRule {
  trigger: EscalationTrigger
  action: EscalationAction
  target_queue_id?: string | null
  target_agent_id?: string | null
  user_ids?: string[]
}

/** Matches the backend's `SlaPolicyResponse`. */
export interface SlaPolicy {
  id: string
  name: string
  description: string | null
  first_response_target_minutes: number | null
  resolution_target_minutes: number | null
  warning_threshold_percent: number
  business_hours_aware: boolean
  escalation_rules: EscalationRule[]
  is_active: boolean
  assigned_queue_count: number
  created_at: string
  updated_at: string
}

export interface SlaPolicyCreateRequest {
  name: string
  description?: string | null
  first_response_target_minutes?: number | null
  resolution_target_minutes?: number | null
  warning_threshold_percent?: number
  business_hours_aware?: boolean
  escalation_rules?: EscalationRule[]
}

export interface SlaPolicyUpdateRequest {
  name?: string
  description?: string | null
  first_response_target_minutes?: number | null
  resolution_target_minutes?: number | null
  warning_threshold_percent?: number
  business_hours_aware?: boolean
  escalation_rules?: EscalationRule[]
  is_active?: boolean
}

/** Matches the backend's `HolidayResponse`. */
export interface Holiday {
  id: string
  name: string
  date: string
  recurs_annually: boolean
}

export interface HolidayCreateRequest {
  name: string
  date: string
  recurs_annually?: boolean
}

export interface HolidayUpdateRequest {
  name?: string
  date?: string
  recurs_annually?: boolean
}

export interface SlaPreviewRequest {
  policy_id: string
  starts_at: string
}

/** Matches the backend's `SlaPreviewResponse`. */
export interface SlaPreview {
  first_response_warning_at: string | null
  first_response_deadline: string | null
  resolution_warning_at: string | null
  resolution_deadline: string | null
}
