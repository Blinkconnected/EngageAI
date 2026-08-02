/**
 * The Conversation Story timeline.
 *
 * The property under test throughout is *trustworthiness*: this is an audit
 * view, so it must render what the backend recorded and nothing more. Several
 * tests below exist to catch the timeline growing a judgement of its own —
 * a severity colour, an inferred consequence, a silent truncation — because
 * each of those is indistinguishable from a fact once it is on the screen.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'
import { ConversationTimeline } from './ConversationTimeline'
import type { TimelineEvent } from './types'

function anEvent(overrides: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    at: '2026-08-01T09:00:00Z',
    stream: 'routing',
    actor: 'Routing',
    actor_kind: 'routing',
    title: 'Queue assigned',
    detail: 'Routed to the "Support" queue because rule "everything" matched.',
    why: [],
    impact: [],
    facts: [],
    decision_id: null,
    code: 'queue_selected',
    severity: 'info',
    ...overrides,
  }
}

const STORY: TimelineEvent[] = [
  anEvent({
    at: '2026-08-01T09:00:00Z',
    stream: 'conversation',
    actor: 'Customer',
    actor_kind: 'customer',
    title: 'Message received',
    detail: 'My invoice is wrong',
    code: 'INBOUND',
  }),
  anEvent(),
  anEvent({
    at: '2026-08-01T09:00:30Z',
    stream: 'ai',
    actor: 'AI',
    actor_kind: 'ai',
    title: 'AI replied',
    detail: 'Let me check that invoice for you.',
    why: ['AI was 70% confident, against a threshold of 60%.'],
    impact: ['The customer received a reply written by AI, not by a person.'],
    facts: [['Confidence', '70%']],
    decision_id: 'dec-1',
    code: 'ai_engaged',
  }),
  anEvent({
    at: '2026-08-02T10:15:00Z',
    stream: 'ownership',
    actor: 'Ada Lovelace',
    actor_kind: 'agent',
    title: 'Became responsible',
    detail: 'AI → Ada Lovelace — they picked it up',
    why: ['They picked it up.'],
    impact: ['Ada Lovelace is now answerable for this conversation.'],
    code: 'picked_by_agent',
  }),
]

function renderTimeline(props: Partial<Parameters<typeof ConversationTimeline>[0]> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <ConversationTimeline events={STORY} {...props} />
    </I18nextProvider>,
  )
}

describe('ConversationTimeline', () => {
  it('renders every event in the order it was given', () => {
    renderTimeline()

    const list = screen.getByRole('list', { name: /conversation timeline/i })
    const titles = within(list)
      .getAllByText(/Message received|Queue assigned|AI replied|Became responsible/)
      .map((node) => node.textContent)

    expect(titles).toEqual([
      'Message received',
      'Queue assigned',
      'AI replied',
      'Became responsible',
    ])
  })

  it('separates days, so a conversation spanning nights reads correctly', () => {
    renderTimeline()

    // Two calendar days in the fixture, so two separators — and no more:
    // a separator per event would be noise rather than structure.
    expect(screen.getAllByText(/2026|Aug|1 Aug|2 Aug/i).length).toBeGreaterThanOrEqual(2)
  })

  it('hides why and impact until an event is expanded', async () => {
    const user = userEvent.setup()
    renderTimeline()

    expect(screen.queryByText(/70% confident/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /show details for AI replied/i }))

    expect(screen.getByText(/70% confident/)).toBeInTheDocument()
    expect(screen.getByText(/received a reply written by AI, not by a person/)).toBeInTheDocument()
  })

  it('offers no expander on an event with nothing more to say', () => {
    renderTimeline({ events: [anEvent()] })

    // An expander that opens onto nothing teaches people the control is
    // meaningless, and then they stop using it where it matters.
    expect(screen.queryByRole('button', { name: /show details/i })).not.toBeInTheDocument()
  })

  it('searches the whole story, not only the titles', async () => {
    const user = userEvent.setup()
    renderTimeline()

    await user.type(screen.getByRole('textbox', { name: /search/i }), 'threshold')

    // Matched on a "why" line, which is the thing somebody actually
    // remembers — not on the event's name.
    expect(await screen.findByText('AI replied')).toBeInTheDocument()
    expect(screen.queryByText('Queue assigned')).not.toBeInTheDocument()
  })

  it('filters by where the event came from, and says how many there are', async () => {
    const user = userEvent.setup()
    renderTimeline()

    await user.click(screen.getByRole('button', { name: /ownership \(1\)/i }))

    expect(screen.getByText('Became responsible')).toBeInTheDocument()
    expect(screen.queryByText('AI replied')).not.toBeInTheDocument()
  })

  it('tells an empty filter apart from an empty conversation', async () => {
    const user = userEvent.setup()
    const { rerender } = renderTimeline()

    await user.type(screen.getByRole('textbox', { name: /search/i }), 'nothing matches this')
    expect(await screen.findByText(/no events match/i)).toBeInTheDocument()

    rerender(
      <I18nextProvider i18n={i18n}>
        <ConversationTimeline
          events={[]}
          gaps={['No routing decisions were recorded for this conversation.']}
        />
      </I18nextProvider>,
    )

    // The second is a fact about the conversation; the first is a control
    // the reader can undo. Rendering both as a blank panel sends people to
    // very different wrong places.
    expect(screen.getByText(/nothing was recorded/i)).toBeInTheDocument()
    expect(screen.getByText(/No routing decisions were recorded/)).toBeInTheDocument()
  })

  it('keeps developer detail out of the way until it is asked for', async () => {
    const user = userEvent.setup()
    renderTimeline()

    await user.click(screen.getByRole('button', { name: /show details for AI replied/i }))
    expect(screen.queryByText('dec-1')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText(/developer details/i))

    expect(screen.getByText(/dec-1/)).toBeInTheDocument()
    expect(screen.getByText('ai_engaged')).toBeInTheDocument()
  })

  it('shows a skeleton while loading and no misleading empty state', () => {
    renderTimeline({ events: [], loading: true })

    expect(screen.getByTestId('timeline-skeleton')).toBeInTheDocument()
    expect(screen.queryByText(/nothing was recorded/i)).not.toBeInTheDocument()
  })

  it('offers a retry when the story could not be loaded', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    renderTimeline({ events: [], error: new Error('boom'), onRetry })

    expect(screen.getByRole('alert')).toHaveTextContent(/could not be loaded/i)
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('is operable from the keyboard alone', async () => {
    const user = userEvent.setup()
    renderTimeline()

    await user.tab()
    expect(screen.getByRole('textbox', { name: /search/i })).toHaveFocus()

    const expander = screen.getByRole('button', { name: /show details for AI replied/i })
    expander.focus()
    expect(expander).toHaveAttribute('aria-expanded', 'false')
    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: /hide details for AI replied/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('says so when it stops rendering, rather than truncating quietly', () => {
    const many = Array.from({ length: 420 }, (_, index) =>
      anEvent({ at: `2026-08-01T09:${String(index % 60).padStart(2, '0')}:00Z` }),
    )
    renderTimeline({ events: many })

    // A silent cap on an audit screen is the same class of problem as an
    // invented event: the reader believes they have seen everything.
    expect(screen.getByRole('alert')).toHaveTextContent(/120 more events are not shown/i)
  })

  it('renders the severity the backend assigned, and never decides one', () => {
    renderTimeline({
      events: [
        anEvent({
          stream: 'sla',
          actor: 'SLA',
          actor_kind: 'sla',
          title: 'SLA breached',
          detail: 'The first response target was missed.',
          code: 'sla_breached',
          severity: 'error',
        }),
        anEvent({
          title: 'Queue assigned',
          detail: 'Routed to Support.',
          // The same words, classified by the backend as ordinary. If the
          // UI were reading the text rather than the field, both rows would
          // look the same — which is the failure this test exists for.
          code: 'queue_selected',
          severity: 'info',
        }),
      ],
    })

    expect(screen.getByText('Error')).toBeInTheDocument()
    expect(screen.queryAllByText(/^Warning$|^Critical$|^Success$/)).toHaveLength(0)
  })

  it('says the severity in words, not only in colour', () => {
    renderTimeline({
      events: [
        anEvent({ title: 'Nothing routed this', severity: 'critical', code: 'left_unrouted' }),
      ],
    })

    // A ring alone is invisible to a screen reader and to a red-green
    // deficiency, on the one column that says whether something went wrong.
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })
})
