/** The Conversation Story, as the backend returns it.
 *
 * Mirrors `api/schemas/inspector.py`. Codes travel beside sentences on
 * purpose: the timeline filters and colours on the code and shows the
 * sentence to a person, so neither can be dropped.
 */

/** Which part of the platform an event came from. Drives filtering. */
export type TimelineStream = 'conversation' | 'routing' | 'ownership' | 'sla' | 'policy' | 'ai'

/** Who or what acted. Drives the icon, never rendered as text — the
 * human-readable name is `actor`. */
export type ActorKind =
  'customer' | 'agent' | 'ai' | 'queue' | 'routing' | 'sla' | 'policy' | 'system'

/** Set by the backend (`domain/severity.py`). The UI renders it and never
 * decides it. */
export type Severity = 'info' | 'success' | 'warning' | 'error' | 'critical'

export interface TimelineEvent {
  at: string
  stream: TimelineStream
  /** "Customer", "AI", "Ada Lovelace" — as a person would say it. */
  actor: string
  actor_kind: ActorKind
  title: string
  detail: string
  /** Why it happened. Empty when the event recorded no reason. */
  why: string[]
  /** What happened next because of it. Every line corresponds to something
   * the backend actually recorded — the timeline never derives these, and
   * must never present them as though it had. */
  impact: string[]
  /** Supporting values for developer mode, as [label, value] pairs. */
  facts: [string, string][]
  /** Links the event to its structured decision record, when it came from
   * one. Absent for messages and ownership rows. */
  decision_id: string | null
  /** The event type code — `queue_selected`, `sla_breached`, `ai_engaged`. */
  code: string | null
  /** How serious the *backend* says this is. Never derived here: the same
   * event must carry the same classification in every client, and a console
   * that worked it out from the wording would be forming a judgement the
   * platform never made. */
  severity: Severity
}

export interface InspectorSummary {
  status: string
  service_name: string | null
  service_version: number | null
  queue_id: string | null
  queue_name: string | null
  runtime_queue_id: string | null
  /** False means the platform does not use runtime lanes yet — distinct
   * from this conversation having failed to get one. */
  runtime_queues_in_use: boolean
  owner_kind: string
  owner_id: string | null
  owner_name: string | null
  owner_label: string
  responsibility: string
  sla_health: string
  ai_state: string
  age_seconds: number
  created_at: string
  customer_name: string | null
  assigned_agent_name: string | null
}

export interface InspectorClock {
  timer: string
  question: string
  state: string
  health: string
  target_minutes: number | null
  /** Which configuration tier set the target, and the sentence explaining it.
   *  A deadline with no author is a number a supervisor cannot act on. */
  target_source: string | null
  target_source_text: string | null
  counted_seconds: number
  remaining_seconds: number | null
  pause_reason: string | null
  pause_text: string | null
  pause_note: string | null
  responsible: string
  settled_at: string | null
}

export interface InspectorOwnershipSpan {
  at: string
  owner_kind: string
  owner_id: string | null
  owner_name: string | null
  owner_label: string
  responsibility: string
  previous_kind: string | null
  previous_label: string | null
  reason: string
  reason_text: string
  note: string | null
  held_seconds: number
}

export interface InspectorAi {
  engaged: boolean
  state: string
  pickup_delay_seconds: number | null
  pickup_eligible_at: string | null
  confidence_threshold: string | null
  threshold_source: string | null
  reasons: string[]
  release_reason: string | null
  resume_eligible: boolean
  resume_blocked_because: string | null
}

export interface InspectorPolicy {
  at: string
  policy: string
  effect: string
  reason: string
  reason_text: string
  source: string
  sentence: string
}

export interface InspectorTechnical {
  conversation_id: string
  company_id: string
  customer_id: string | null
  channel_type: string | null
  external_thread_id: string | null
  service_id: string | null
  service_version_id: string | null
  service_version: number | null
  customer_context_version_id: string | null
  context_bound_at: string | null
  context_binding_reason: string | null
  /** Artefacts this platform does not version. Listed so an engineer stops
   * looking for a version that was never minted. */
  unversioned: string[]
}

export interface InspectorDecision {
  id: string
  at: string
  kind: string
  outcome: string
  reason: string
  sentence: string
  policy: string | null
  policy_reason: string | null
  policy_source: string | null
  policy_text: string | null
  matched_rule_name: string | null
  matched_rule_priority: number | null
  rules_evaluated: number
  strategy: string | null
  candidates_considered: number
  ai_pickup_delay_seconds: number | null
}

export interface ConversationInspection {
  summary: InspectorSummary
  timeline: TimelineEvent[]
  decisions: InspectorDecision[]
  ownership: InspectorOwnershipSpan[]
  clocks: InspectorClock[]
  sla_health: string
  ai: InspectorAi
  policies: InspectorPolicy[]
  technical: InspectorTechnical
  generated_at: string
  /** What the platform does not know about this conversation. An empty
   * section and an unrecorded one look identical otherwise. */
  gaps: string[]
}

/** The filter chips, in the order they read. `all` is not a stream — it is
 * the absence of a filter. */
export const TIMELINE_STREAMS: TimelineStream[] = [
  'conversation',
  'routing',
  'ownership',
  'sla',
  'ai',
  'policy',
]
