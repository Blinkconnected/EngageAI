/**
 * The one SLA thing an agent sees without opening a conversation.
 *
 * Tested at the band level rather than by snapshot, because the property that
 * matters is which conversations shout and which stay quiet — a chip on every
 * row is the same as a chip on none.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'
import { SlaIndicator } from './ConversationCells'
import type { Conversation, SlaHealth } from './types'

function conversationWith(health: SlaHealth): Conversation {
  return { id: 'c1', sla_health: health } as Conversation
}

function renderFor(health: SlaHealth) {
  return render(
    <I18nextProvider i18n={i18n}>
      <SlaIndicator conversation={conversationWith(health)} />
    </I18nextProvider>,
  )
}

describe('SlaIndicator', () => {
  it('says nothing at all when the conversation is on track', () => {
    const { container } = renderFor('healthy')
    // The common case, and the reason the other three read as signal. This
    // includes a conversation paused waiting on the customer: the business
    // is not late while the ball is with them.
    expect(container).toBeEmptyDOMElement()
  })

  it.each([
    ['attention', 'Attention'],
    ['at_risk', 'At risk'],
    ['breached', 'Breached'],
  ] as const)('shows %s as "%s"', (health, label) => {
    renderFor(health)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('never renders a raw translation key', () => {
    // Production must never show `InboxPage.slaHealth.breached.short` to a
    // customer-facing agent — the failure mode of a key added in code and
    // forgotten in the bundle.
    for (const health of ['attention', 'at_risk', 'breached'] as const) {
      const { container, unmount } = renderFor(health)
      expect(container.textContent).not.toMatch(/InboxPage\./)
      unmount()
    }
  })

  it('survives a conversation from before the SLA engine', () => {
    // An older cached payload has no sla_health at all. Undefined must read
    // as "nothing to show", never as an emergency.
    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <SlaIndicator conversation={{ id: 'c1' } as Conversation} />
      </I18nextProvider>,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
