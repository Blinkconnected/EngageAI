/**
 * The Inspector's cards, and one property in particular: a deadline has an
 * author.
 *
 * "Due in three minutes" is a number a supervisor has to act on, and acting on
 * it means knowing which screen changes it — the service, the queue, or
 * nothing at all because nobody configured one. The platform resolves that
 * down four tiers and records which one answered; this is where a person can
 * finally see it.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'
import { InspectorCards } from './InspectorCards'
import type { ConversationInspection, InspectorClock } from './types'

function aClock(overrides: Partial<InspectorClock> = {}): InspectorClock {
  return {
    timer: 'first_response',
    question: 'How long until the customer receives the first meaningful reply?',
    state: 'running',
    health: 'healthy',
    target_minutes: 3,
    target_source: 'queue',
    target_source_text: 'set by the queue it is waiting in',
    counted_seconds: 12,
    remaining_seconds: 168,
    pause_reason: null,
    pause_text: null,
    pause_note: null,
    responsible: 'the Support queue',
    settled_at: null,
    ...overrides,
  }
}

function anInspection(clocks: InspectorClock[]): ConversationInspection {
  return {
    summary: {
      status: 'waiting',
      service_name: null,
      service_version: null,
      queue_id: 'q1',
      queue_name: 'Support',
      runtime_queue_id: null,
      runtime_queues_in_use: false,
      owner_kind: 'queue',
      owner_id: 'q1',
      owner_name: 'Support',
      owner_label: 'the Support queue',
      responsibility: 'pickup',
      sla_health: 'healthy',
      ai_state: 'not_engaged',
      age_seconds: 12,
      created_at: '2026-08-01T09:00:00Z',
      customer_name: 'Grace Blake',
      assigned_agent_name: null,
    },
    timeline: [],
    decisions: [],
    ownership: [],
    clocks,
    sla_health: 'healthy',
    ai: {
      engaged: false,
      state: 'not_engaged',
      pickup_delay_seconds: null,
      pickup_eligible_at: null,
      confidence_threshold: null,
      threshold_source: null,
      reasons: [],
      release_reason: null,
      resume_eligible: false,
      resume_blocked_because: null,
    },
    policies: [],
    technical: {
      conversation_id: 'c1',
      company_id: 'co1',
      customer_id: null,
      channel_type: 'whatsapp',
      external_thread_id: null,
      service_id: null,
      service_version_id: null,
      service_version: null,
      customer_context_version_id: null,
      context_bound_at: null,
      context_binding_reason: null,
      unversioned: [],
    },
    generated_at: '2026-08-01T09:00:12Z',
    gaps: [],
  }
}

function renderCards(clocks: InspectorClock[]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <InspectorCards inspection={anInspection(clocks)} />
    </I18nextProvider>,
  )
}

describe('InspectorCards — where a deadline came from', () => {
  it('names the tier that set the target', async () => {
    renderCards([aClock({ target_source: 'queue' })])

    expect(await screen.findByText(/set by the queue/i)).toBeInTheDocument()
  })

  it('distinguishes a configured deadline from a platform default', async () => {
    // The difference an administrator most needs: one is a promise their
    // company made, the other is the platform filling a gap. Rendering them
    // identically would let somebody believe they had configured an SLA they
    // had not.
    renderCards([aClock({ target_source: 'platform_default' })])

    expect(await screen.findByText(/platform default/i)).toBeInTheDocument()
    expect(screen.getByText(/nothing is configured/i)).toBeInTheDocument()
  })

  it('says nothing at all when the tier was not recorded', async () => {
    // A clock started before provenance was carried. Inventing "platform
    // default" for it would be the Inspector guessing, which is the one thing
    // this screen must never do.
    renderCards([aClock({ target_source: null, target_source_text: null })])

    // Matched against the tier sentences themselves rather than a loose
    // phrase: the AI card carries an unrelated "Threshold set by" label, and
    // a regex broad enough to catch that would pass for the wrong reason.
    expect(screen.queryByText(/set by the queue it is waiting in/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/set by this conversation's service/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/platform default/i)).not.toBeInTheDocument()
  })

  it('never shows a raw tier code to a reader', async () => {
    // Same defect as a raw translation key: technically correct, humanly
    // useless. Every tier has wording, enforced on the backend too.
    renderCards([
      aClock({ timer: 'first_response', target_source: 'service' }),
      aClock({ timer: 'resolution', target_source: 'company' }),
    ])

    const cards = await screen.findByText(/set by this conversation's service/i)
    expect(cards).toBeInTheDocument()
    expect(screen.getByText(/set company-wide/i)).toBeInTheDocument()
    expect(screen.queryByText('platform_default')).not.toBeInTheDocument()
    expect(screen.queryByText('service')).not.toBeInTheDocument()
  })

  it('keeps the target beside the tier, so the number and its author read together', async () => {
    renderCards([aClock({ target_minutes: 3, target_source: 'queue' })])

    const region = screen.getByText(/set by the queue/i).closest('div')
    expect(region).not.toBeNull()
    expect(within(region as HTMLElement).getByText(/3 min/i)).toBeInTheDocument()
  })
})
