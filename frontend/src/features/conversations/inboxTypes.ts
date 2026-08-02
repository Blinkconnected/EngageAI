/** The Inbox's operational vocabulary, as the backend defines it.
 *
 * Mirrors `domain/inbox_views.py` and `domain/operational_state.py`. Neither
 * is computed here: the browser renders what the platform decided, so the
 * Inbox and the Conversation Story can never describe the same conversation
 * differently.
 */

/** A work queue. Not a filter — an operational question with one answer. */
export type InboxView =
  | 'active'
  | 'needs_attention'
  | 'waiting_pickup'
  | 'mine'
  | 'ai_working'
  | 'waiting_customer'
  | 'at_risk'
  | 'breached'
  | 'resolved_today'

/** What a conversation is waiting on. Described, never prescribed. */
export type OperationalState =
  | 'waiting_for_pickup'
  | 'waiting_for_agent'
  | 'waiting_for_customer'
  | 'ready_for_reply'
  | 'ai_responding'
  | 'ai_pickup_delay'
  | 'ai_resume_delay'
  | 'transferred'
  | 'escalated'
  | 'awaiting_resolution'
  | 'resolved'
  | 'awaiting_feedback'
  | 'closed'

/** How many conversations are in each queue, company-wide. */
export type Workload = Record<InboxView, number>

/** The queues an agent moves between, in the order they triage in: what is
 * broken, what nobody has, what is mine, what AI has, what we are waiting on,
 * and finally what is done. `active` is the denominator, not a queue. */
export const WORK_QUEUES: InboxView[] = [
  'needs_attention',
  'waiting_pickup',
  'mine',
  'ai_working',
  'waiting_customer',
  'at_risk',
  'breached',
  'resolved_today',
]
