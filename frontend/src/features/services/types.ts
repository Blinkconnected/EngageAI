/** A thing a customer can be helped with — Billing, Technical Support, Sales.
 *
 * The *identity*: renamed, archived, reordered. Everything a running
 * conversation reads lives on a version instead, so that editing this row
 * cannot reach backwards into conversations already in progress. */
export interface Service {
  id: string
  /** A stable machine handle. Separate from `name` because an external
   * system selecting by name breaks the first time somebody fixes a typo. */
  code: string
  name: string
  description: string | null
  is_active: boolean
  display_order: number
  current_version_id: string | null
}

/** One frozen configuration. Conversations are bound to a version and read it
 * for their whole life, which is why these are never edited, only superseded. */
export interface ServiceVersion {
  id: string
  version: number
  name: string
  logical_queue_id: string | null
  logical_queue_name: string | null
  overflow_strategy: string
  ai_overflow_policy: string
  /** Four independent clocks. `null` means "not measured" and is different
   * from `0`, which means "breached the moment it starts". */
  sla_queue_minutes: number | null
  sla_first_response_minutes: number | null
  sla_next_response_minutes: number | null
  sla_resolution_minutes: number | null
  ai_enabled: boolean
  ai_pickup_delay_seconds: number
  ai_resume_delay_seconds: number
  /** A string, not a number: a float would let two values differing in the
   * last binary place straddle the threshold they are compared against. */
  /** `null` means this service defers to the company-wide threshold. */
  ai_confidence_threshold: string | null
  extras: Record<string, unknown>
  created_at: string | null
  created_by_user_id: string | null
  /** Why this version exists, in an operator's words. */
  change_note: string | null
}

export interface ServiceDetail {
  service: Service
  current: ServiceVersion | null
}

export interface ServiceSaved extends ServiceDetail {
  /** Whether this edit created a new version. Shown to the operator, because
   * somebody who cannot tell "saved" from "version 4 created" cannot predict
   * which of their edits reach conversations already running. */
  version_minted: boolean
}

export interface SlaTargetsPayload {
  queue_minutes: number | null
  first_response_minutes: number | null
  next_response_minutes: number | null
  resolution_minutes: number | null
}

export interface AiPolicyPayload {
  enabled: boolean
  pickup_delay_seconds: number
  resume_delay_seconds: number
  confidence_threshold: string
}

export interface ServiceCreateRequest {
  code: string
  name: string
  description?: string | null
  display_order?: number
  logical_queue_id?: string | null
  sla?: Partial<SlaTargetsPayload>
  ai?: Partial<AiPolicyPayload>
}

/** Every field optional, and only what changed is sent: an omitted field
 * means *unchanged*, never *cleared*. Sending the whole form back would make
 * an untouched SLA target look like a deliberate decision to stop measuring
 * it. */
export interface ServiceUpdateRequest {
  code?: string
  name?: string
  description?: string | null
  is_active?: boolean
  display_order?: number
  logical_queue_id?: string | null
  sla?: SlaTargetsPayload
  ai?: AiPolicyPayload
  change_note?: string
}
