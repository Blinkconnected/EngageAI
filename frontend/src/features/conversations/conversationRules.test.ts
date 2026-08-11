import { describe, expect, it } from 'vitest'
import { isFinished, isPickable } from './conversationRules'
import type { Conversation, ConversationStatus } from './types'

type PickInput = Pick<
  Conversation,
  'status' | 'queue_id' | 'assigned_agent_id' | 'autopilot_active'
>

function conversation(overrides: Partial<PickInput> = {}): PickInput {
  return {
    status: 'waiting',
    queue_id: 'queue-1',
    assigned_agent_id: null,
    autopilot_active: false,
    ...overrides,
  }
}

const OPEN: ConversationStatus[] = [
  'new',
  'waiting',
  'in_progress',
  'waiting_customer',
  'waiting_agent',
  'customer_feedback',
]

describe('isFinished', () => {
  it.each(['resolved', 'closed'] as ConversationStatus[])('%s is finished', (status) => {
    expect(isFinished(status)).toBe(true)
  })

  it.each(OPEN)('%s is not finished', (status) => {
    expect(isFinished(status)).toBe(false)
  })
})

describe('isPickable', () => {
  it('is true for an unclaimed conversation sitting in a queue', () => {
    expect(isPickable(conversation())).toBe(true)
  })

  // The regression this module exists for. A finished conversation keeps
  // its queue_id and has no assigned agent, so every "is nobody on it?"
  // test says yes — and the server answers 409.
  it.each(['resolved', 'closed'] as ConversationStatus[])(
    'is false for a %s conversation even though nobody owns it',
    (status) => {
      expect(isPickable(conversation({ status }))).toBe(false)
    },
  )

  it('is false once an agent holds it', () => {
    expect(isPickable(conversation({ assigned_agent_id: 'agent-1' }))).toBe(false)
  })

  it('is false while autopilot is answering', () => {
    expect(isPickable(conversation({ autopilot_active: true }))).toBe(false)
  })

  it('is false with no queue to pick out of', () => {
    expect(isPickable(conversation({ queue_id: null }))).toBe(false)
  })

  it.each(OPEN)('is true for %s', (status) => {
    expect(isPickable(conversation({ status }))).toBe(true)
  })
})
