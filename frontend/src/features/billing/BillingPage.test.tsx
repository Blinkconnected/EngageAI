import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { BillingPage } from './BillingPage'
import type { BillingOverview } from './types'

const PLAN = {
  id: 'plan-1',
  name: 'Business',
  description: 'For growing teams',
  amount: '49.00',
  currency: 'USD',
  interval: 'month' as const,
  is_active: true,
  sort_order: 0,
  features: null,
  is_purchasable: true,
}

function mockOverview(overrides: Partial<BillingOverview> = {}) {
  const body: BillingOverview = {
    is_configured: true,
    subscription: null,
    plans: [PLAN],
    payments: [],
    ...overrides,
  }
  server.use(http.get(`${API_BASE_URL}/billing`, () => HttpResponse.json(body)))
}

describe('BillingPage', () => {
  // Cleared in `beforeEach`, not `afterEach`. Vitest runs afterEach
  // hooks in reverse registration order, so a hook declared here runs
  // *before* React Testing Library's auto-cleanup — the previous test's
  // component is still mounted, and clearing the cache under it makes
  // its live observer immediately refetch and repopulate the cache with
  // that test's data. The next test then renders stale data from a
  // handler it never registered. Clearing here instead runs after the
  // previous test is fully torn down.
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(() => {
    store.dispatch(loggedOut())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('offers the available plans when the company has no subscription', async () => {
    mockOverview()
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText('Business')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /subscribe/i })).toBeEnabled()
  })

  it('explains itself instead of offering a button that can only fail', async () => {
    // An installation whose operator never connected PayPal. Showing a
    // Subscribe button here would produce a 503 and no explanation.
    mockOverview({ is_configured: false, plans: [] })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText(/billing isn't set up/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /subscribe/i })).not.toBeInTheDocument()
  })

  it('sends the customer to PayPal to approve the subscription', async () => {
    const user = userEvent.setup()
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockOverview()
    server.use(
      http.post(`${API_BASE_URL}/billing/subscribe`, () =>
        HttpResponse.json({
          id: 'sub-1',
          company_id: 'co-1',
          plan_id: PLAN.id,
          plan_name: PLAN.name,
          amount: PLAN.amount,
          currency: 'USD',
          interval: 'month',
          status: 'approval_pending',
          approval_url: 'https://www.sandbox.paypal.com/approve/I-1',
          current_period_end: null,
          started_at: null,
          cancelled_at: null,
          failed_payment_count: 0,
        }),
      ),
    )
    renderAuthenticated(<BillingPage />)
    await screen.findByText('Business')

    await user.click(screen.getByRole('button', { name: /subscribe/i }))

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://www.sandbox.paypal.com/approve/I-1'),
    )
  })

  it('says a pending subscription is not active yet, and offers the way to finish', async () => {
    // The state a customer lands in if they close PayPal's window
    // mid-checkout. Without the link they would be stranded.
    mockOverview({
      subscription: {
        id: 'sub-1',
        company_id: 'co-1',
        plan_id: PLAN.id,
        plan_name: 'Business',
        amount: '49.00',
        currency: 'USD',
        interval: 'month',
        status: 'approval_pending',
        approval_url: 'https://www.sandbox.paypal.com/approve/I-1',
        current_period_end: null,
        started_at: null,
        cancelled_at: null,
        failed_payment_count: 0,
      },
    })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText(/isn't active yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /finish in paypal/i })).toHaveAttribute(
      'href',
      'https://www.sandbox.paypal.com/approve/I-1',
    )
  })

  it('warns about a failed payment without claiming the workspace is gone', async () => {
    mockOverview({
      subscription: {
        id: 'sub-1',
        company_id: 'co-1',
        plan_id: PLAN.id,
        plan_name: 'Business',
        amount: '49.00',
        currency: 'USD',
        interval: 'month',
        status: 'past_due',
        approval_url: null,
        current_period_end: '2026-08-29T00:00:00Z',
        started_at: '2026-07-01T00:00:00Z',
        cancelled_at: null,
        failed_payment_count: 1,
      },
    })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText(/didn't go through/i)).toBeInTheDocument()
    expect(screen.getByText(/will try again/i)).toBeInTheDocument()
  })

  it('says cancelling keeps access until the paid period ends', async () => {
    const user = userEvent.setup()
    mockOverview({
      subscription: {
        id: 'sub-1',
        company_id: 'co-1',
        plan_id: PLAN.id,
        plan_name: 'Business',
        amount: '49.00',
        currency: 'USD',
        interval: 'month',
        status: 'active',
        approval_url: null,
        current_period_end: '2026-08-29T00:00:00Z',
        started_at: '2026-07-01T00:00:00Z',
        cancelled_at: null,
        failed_payment_count: 0,
      },
    })
    renderAuthenticated(<BillingPage />)
    await screen.findByText('Business')

    await user.click(screen.getByRole('button', { name: /cancel subscription/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/keep full access until the end/i)).toBeInTheDocument()
  })

  it('lists past payments', async () => {
    mockOverview({
      payments: [
        {
          id: 'pay-1',
          amount: '49.00',
          currency: 'USD',
          status: 'completed',
          occurred_at: '2026-07-01T00:00:00Z',
        },
      ],
    })
    renderAuthenticated(<BillingPage />)

    const row = (await screen.findByText('Paid')).closest('tr') as HTMLElement
    expect(within(row).getByText(/49\.00/)).toBeInTheDocument()
  })

  it('shows a retryable error when billing fails to load', async () => {
    server.use(
      http.get(`${API_BASE_URL}/billing`, () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
    )
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
