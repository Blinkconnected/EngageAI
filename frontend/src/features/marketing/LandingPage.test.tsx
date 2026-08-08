import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test/renderWithProviders'
import { LandingPage } from './LandingPage'

/**
 * The landing page is the first thing an anonymous visitor sees, so the
 * things worth testing are the ones that would embarrass us if they
 * broke: can somebody reach sign-in, does it describe the product, and
 * is it usable by somebody who cannot see it.
 *
 * Marketing copy itself is deliberately not asserted word for word —
 * that turns every wording change into a failing test without catching
 * a single real defect.
 */
describe('LandingPage', () => {
  it('offers a way to sign in and a way to start', () => {
    renderWithProviders(<LandingPage />)

    // Both appear more than once (header, hero, footer) — that is the
    // point, so a visitor scrolled halfway down does not have to go back.
    expect(screen.getAllByRole('link', { name: /sign in/i }).length).toBeGreaterThan(0)
    expect(
      screen.getAllByRole('link', { name: /get started|create a workspace/i }).length,
    ).toBeGreaterThan(0)
  })

  it('points sign-in and registration at the real routes', () => {
    renderWithProviders(<LandingPage />)

    const signIn = screen.getAllByRole('link', { name: /sign in/i })[0]
    expect(signIn).toHaveAttribute('href', '/login')

    const start = screen.getAllByRole('link', { name: /create a workspace/i })[0]
    expect(start).toHaveAttribute('href', '/register')
  })

  it('names every channel the product actually supports', () => {
    renderWithProviders(<LandingPage />)

    // If a channel is added or removed in the product, this list should
    // change with it — a landing page naming a channel that does not
    // exist is the failure this whole page was written to avoid.
    for (const channel of [
      'WhatsApp',
      'Facebook Messenger',
      'Instagram',
      'Telegram',
      'Email',
      'SMS',
      'Web Chat',
    ]) {
      // getAllBy: the hero illustration names some channels too, which
      // is the point — the same names appear in the product.
      expect(screen.getAllByText(channel).length).toBeGreaterThan(0)
    }
  })

  it('says what the product does not do yet', () => {
    renderWithProviders(<LandingPage />)

    // A prospect discovering after purchase that there is no mobile app
    // is a refund. Discovering it here is a qualified lead or an honest
    // no — both better outcomes.
    expect(screen.getByText(/does not do yet/i)).toBeInTheDocument()
    expect(screen.getByText(/no mobile app/i)).toBeInTheDocument()
  })

  it('uses one first-level heading', () => {
    renderWithProviders(<LandingPage />)

    // Search engines and screen readers both rely on there being exactly
    // one h1, and this page has enough sections to make it easy to add a
    // second by accident.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('renders translated copy, never raw translation keys', () => {
    const { container } = renderWithProviders(<LandingPage />)

    // Written after shipping a locale edit that replaced the hero object
    // instead of merging into it, deleting hero.title and hero.subtitle.
    // Every key still existed in both languages, so a parity check passed
    // and the page rendered "LandingPage.hero.title" to real visitors.
    // Any untranslated key on this page now fails here.
    expect(container.textContent).not.toMatch(/LandingPage\.|ProductMockup\./)
  })

  it('has no accessibility violations', async () => {
    const { container } = renderWithProviders(<LandingPage />)

    expect(await axe(container)).toHaveNoViolations()
  })
})
