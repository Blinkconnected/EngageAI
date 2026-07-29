import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { PlatformPricingPage } from './PlatformPricingPage'

const CONVERSATION = {
  metric_code: 'CONVERSATION',
  display_name: 'Conversation',
  unit: 'conversation' as const,
  unit_amount: '0.050000',
  currency: 'USD',
  scope: 'global' as const,
  rate_id: 'rate-1',
  effective_from: '2026-01-01T00:00:00Z',
  effective_until: null,
  shadowed: [],
}

const AUTOPILOT = {
  metric_code: 'AI_AUTOPILOT',
  display_name: 'AI Autopilot reply',
  unit: 'reply' as const,
  unit_amount: null,
  currency: null,
  scope: null,
  rate_id: null,
  effective_from: null,
  effective_until: null,
  shadowed: [],
}

function mockPricing(items = [CONVERSATION, AUTOPILOT], overrides: Record<string, unknown> = {}) {
  server.use(
    http.get(`${API_BASE_URL}/platform/pricing/effective`, () =>
      HttpResponse.json({
        resolved_at: '2026-07-29T12:00:00Z',
        company_id: null,
        profile_id: null,
        profile_name: null,
        currency: 'USD',
        items,
        ...overrides,
      }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/profiles`, () =>
      HttpResponse.json([
        { id: 'p-default', key: 'default', name: 'Default', description: null, is_system: true, is_active: true, sort_order: 0 },
        { id: 'p-ent', key: 'enterprise', name: 'Enterprise', description: null, is_system: false, is_active: true, sort_order: 30 },
      ]),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/health`, () =>
      HttpResponse.json({
        ok: false,
        metrics: [
          { metric_code: 'CONVERSATION', display_name: 'Conversation', covered: true, reason: null },
          { metric_code: 'AI_AUTOPILOT', display_name: 'AI Autopilot reply', covered: false, reason: 'no_global_rate' },
        ],
      }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/history`, () => HttpResponse.json([])),
  )
}

describe('PlatformPricingPage', () => {
  // Cleared before, not after: Vitest runs afterEach hooks declared here
  // before RTL's cleanup, so clearing then makes the still-mounted
  // observer refetch and repopulate with the previous test's data.
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(() => {
    store.dispatch(loggedOut())
  })

  it('shows the price for each metric with where it came from', async () => {
    mockPricing()
    renderAuthenticated(<PlatformPricingPage />)

    const row = (await screen.findByText('Conversation')).closest('tr') as HTMLElement
    expect(within(row).getByText('$0.05')).toBeInTheDocument()
    expect(within(row).getByText(/global default/i)).toBeInTheDocument()
  })

  it('shows a sub-cent rate at full precision instead of rounding it to nothing', async () => {
    // $0.0005 and $0.05 are a hundredfold apart; at two decimal places
    // they render as "$0.00" and "$0.05", making one look free.
    mockPricing([{ ...CONVERSATION, unit_amount: '0.000500' }])
    renderAuthenticated(<PlatformPricingPage />)

    expect(await screen.findByText('$0.0005')).toBeInTheDocument()
  })

  it('distinguishes an unpriced metric from a free one', async () => {
    mockPricing()
    renderAuthenticated(<PlatformPricingPage />)

    const row = (await screen.findByText('AI Autopilot reply')).closest('tr') as HTMLElement
    expect(within(row).getByText(/not set/i)).toBeInTheDocument()
    expect(within(row).queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('warns when a measurable metric has no price at all', async () => {
    // Harmless while nothing meters anything; an outage the moment usage
    // metering ships. Surfaced now rather than discovered then.
    mockPricing()
    renderAuthenticated(<PlatformPricingPage />)

    expect(await screen.findByText(/no price is configured for/i)).toBeInTheDocument()
  })

  it('sends the current rate id when saving, so a concurrent edit is refused', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    mockPricing()
    server.use(
      http.put(`${API_BASE_URL}/platform/pricing/global/metrics/:metric`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ rate: {}, resolved: null }, { status: 201 })
      }),
    )
    renderAuthenticated(<PlatformPricingPage />)
    const row = (await screen.findByText('Conversation')).closest('tr') as HTMLElement

    await user.click(within(row).getByRole('button', { name: /edit/i }))
    const dialog = await screen.findByRole('dialog')
    const amount = within(dialog).getByLabelText(/price per unit/i)
    await user.clear(amount)
    await user.type(amount, '0.055')
    await user.click(within(dialog).getByRole('button', { name: /save price/i }))

    await waitFor(() => expect(body.unit_amount).toBe('0.055'))
    expect(body.expected_current_rate_id).toBe('rate-1')
  })

  it('claims no current rate when the metric has never been priced', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    mockPricing()
    server.use(
      http.put(`${API_BASE_URL}/platform/pricing/global/metrics/:metric`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ rate: {}, resolved: null }, { status: 201 })
      }),
    )
    renderAuthenticated(<PlatformPricingPage />)
    const row = (await screen.findByText('AI Autopilot reply')).closest('tr') as HTMLElement

    await user.click(within(row).getByRole('button', { name: /edit/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/price per unit/i), '0.01')
    await user.click(within(dialog).getByRole('button', { name: /save price/i }))

    await waitFor(() => expect(body.expect_no_current_rate).toBe(true))
    expect(body.expected_current_rate_id).toBeUndefined()
  })

  it('tells the operator that changing a price never re-rates past usage', async () => {
    const user = userEvent.setup()
    mockPricing()
    renderAuthenticated(<PlatformPricingPage />)
    const row = (await screen.findByText('Conversation')).closest('tr') as HTMLElement

    await user.click(within(row).getByRole('button', { name: /edit/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/never re-rates past usage/i)).toBeInTheDocument()
  })

  it('surfaces a rejected save instead of closing as though it worked', async () => {
    const user = userEvent.setup()
    mockPricing()
    server.use(
      http.put(`${API_BASE_URL}/platform/pricing/global/metrics/:metric`, () =>
        HttpResponse.json(
          { detail: 'The current price changed since you loaded it (now: 0.060000).' },
          { status: 409 },
        ),
      ),
    )
    renderAuthenticated(<PlatformPricingPage />)
    const row = (await screen.findByText('Conversation')).closest('tr') as HTMLElement

    await user.click(within(row).getByRole('button', { name: /edit/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/price per unit/i), '5')
    await user.click(within(dialog).getByRole('button', { name: /save price/i }))

    expect(await screen.findByText(/changed since you loaded it/i)).toBeInTheDocument()
  })

  it('offers pricing profiles but not the system Default, which has no prices of its own', async () => {
    mockPricing()
    renderAuthenticated(<PlatformPricingPage />)
    await screen.findByText('Conversation')

    const select = screen.getByLabelText(/showing prices for/i)
    await userEvent.setup().click(select)

    expect(await screen.findByRole('option', { name: 'Enterprise' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Default' })).not.toBeInTheDocument()
  })
})
