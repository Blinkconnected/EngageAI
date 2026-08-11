/** Rules the interface must agree with the server about.
 *
 * Anything here exists because the screen offers an action and the API
 * decides whether it was allowed. When the two disagree the user gets a
 * button that fails — which reads as the product being broken, not as a
 * rule being enforced.
 */

import type { Conversation, ConversationStatus } from './types'

/** Finished. The conversation keeps its `queue_id` for reporting, so the
 * queue alone never tells you whether there is work left to do. */
const FINISHED: readonly ConversationStatus[] = ['resolved', 'closed']

export function isFinished(status: ConversationStatus): boolean {
  return FINISHED.includes(status)
}

/**
 * Whether "Pick up" can succeed, mirroring `ConversationService.pick`:
 * a conversation must be in a queue, and must not be finished.
 *
 * The status check is the part that is easy to leave out, and leaving it
 * out is invisible in development. A resolved conversation has no
 * assigned agent, so "is nobody working on this?" answers *yes* for every
 * conversation that has already been dealt with — and the Inbox offered
 * a green Pick up on all of them, which 409'd on click.
 */
export function isPickable(
  conversation: Pick<
    Conversation,
    'status' | 'queue_id' | 'assigned_agent_id' | 'autopilot_active'
  >,
): boolean {
  if (conversation.assigned_agent_id != null) return false
  if (conversation.autopilot_active) return false
  if (conversation.queue_id == null) return false
  return !isFinished(conversation.status)
}
