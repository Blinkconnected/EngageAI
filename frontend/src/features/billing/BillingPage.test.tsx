import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { queryClient } from '../../app/queryClient'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { BillingPage } from './BillingPage'
import type {
  BillingDashboard,
  BillingEstimate,
  DailySeries,
  MetricCost,
  Projection,
} from './types'

const CONVERSATIONS: MetricCost = {
  metric_code: 'CONVERSATION',
  display_name: 'Conversation',
  unit: 'conversation',
  quantity: '240.000000',
  unit_amount: '0.050000',
  estimated_cost: '7.000000',
  currency: 'USD',
  included_quantity: '100.000000',
  billable_quantity: '140.000000',
  share_percent: '87.5',
}

const AI_REPLIES: MetricCost = {
  metric_code: 'AI_REPLY',
  display_name: 'AI-assisted reply',
  unit: 'reply',
  quantity: '50.000000',
  unit_amount: '0.020000',
  estimated_cost: '1.000000',
  currency: 'USD',
  included_quantity: '0.000000',
  billable_quantity: '50.000000',
  share_percent: '12.5',
}

const ROLLING: Projection = {
  strategy: 'rolling_7_day',
  effective_strategy: 'rolling_7_day',
  fell_back: false,
  method: 'Rolling 7-Day Average',
  method_explanation: 'The average of the last 7 complete days, applied to the days remaining.',
  projected_total: '31.000000',
  actual_to_date: '8.000000',
  daily_average: '1.000000',
  days_measured: 7,
  days_elapsed: 8,
  days_in_period: 31,
  days_remaining: 23,
  currency: 'USD',
  unavailable_reason: null,
  unavailable_explanation: null,
}

const DAILY_AVERAGE: Projection = {
  ...ROLLING,
  strategy: 'daily_average',
  effective_strategy: 'daily_average',
  method: 'Current Daily Average',
  projected_total: '29.000000',
}

const FELL_BACK: Projection = {
  ...ROLLING,
  effective_strategy: 'daily_average',
  fell_back: true,
  method: 'Current Daily Average',
  method_explanation: 'The average of every complete day in this period so far.',
  days_measured: 3,
}

const LINEAR: Projection = {
  ...ROLLING,
  strategy: 'linear_pace',
  effective_strategy: 'linear_pace',
  method: 'Linear Projection (current pace)',
  projected_total: '34.000000',
}

const ESTIMATE: BillingEstimate = {
  as_of: '2026-07-08T14:30:00Z',
  currency: 'USD',
  estimated_today: '1.250000',
  estimated_month_to_date: '8.000000',
  today: [CONVERSATIONS],
  month_to_date: [CONVERSATIONS, AI_REPLIES],
  projection: ROLLING,
  data_as_of: '2026-07-08T14:29:45Z',
}

const DAILY: DailySeries = {
  window: '30d',
  start: '2026-07-01',
  end: '2026-07-08',
  currency: 'USD',
  days: [
    {
      day: '2026-07-01',
      estimated_cost: '1.000000',
      quantity: '20.000000',
      currency: 'USD',
      final: true,
      projected_total_snapshot: '30.000000',
    },
    {
      day: '2026-07-02',
      estimated_cost: '0.000000',
      quantity: '0.000000',
      currency: 'USD',
      final: false,
      projected_total_snapshot: null,
    },
    {
      day: '2026-07-08',
      estimated_cost: '1.250000',
      quantity: '25.000000',
      currency: 'USD',
      final: false,
      projected_total_snapshot: '31.000000',
    },
  ],
  data_starts_on: '2026-07-01',
  total_estimated_cost: '8.000000',
}

const DASHBOARD: BillingDashboard = {
  overview: {
    company_name: 'Blink Connected',
    currency: 'USD',
    currency_symbol: '$',
    currency_decimal_places: 2,
    billing_status: 'active',
    status_detail: 'No outstanding balance. Nothing to do.',
    status_detail_code: 'nothing_due',
    status_detail_params: {},
    period_start: '2026-07-01',
    period_last_day: '2026-07-31',
    days_elapsed: 8,
    days_remaining: 23,
    estimated_today: '1.250000',
    estimated_month_to_date: '8.000000',
    projected_total: '31.000000',
    projection_method: 'Rolling 7-Day Average',
    outstanding_balance: '0.000000',
    credit_balance: '0.000000',
    next_invoice_on: '2026-08-01',
    next_payment_due_on: '2026-08-22',
    no_open_period: false,
  },
  estimate: ESTIMATE,
  daily: DAILY,
  timeline: [
    {
      key: 'period_started',
      label: 'Billing period started',
      at: '2026-07-01',
      state: 'done',
      detail: 'Usage began accumulating.',
    },
    {
      key: 'accruing',
      label: 'Usage accruing',
      at: '2026-07-08',
      state: 'current',
      detail: 'Charges shown are estimates until the period closes.',
    },
    {
      key: 'suspension_risk',
      label: 'Service suspended if unpaid',
      at: '2026-09-12',
      state: 'upcoming',
      detail: '21 days after the due date. Reminders are sent before this.',
    },
  ],
  invoices: [
    {
      id: 'inv-1',
      invoice_number: 'INV-2026-000123',
      status: 'issued',
      period_start: '2026-06-01T00:00:00Z',
      period_end: '2026-07-01T00:00:00Z',
      issued_at: '2026-07-01T02:00:00Z',
      due_date: '2026-07-22',
      total_amount: '24.000000',
      amount_paid: '0.000000',
      amount_credited: '0.000000',
      amount_outstanding: '24.000000',
      currency: 'USD',
      days_overdue: 0,
    },
  ],
  payment_methods: [
    {
      code: 'paypal',
      label: 'PayPal',
      available: false,
      self_serve: true,
      unavailable_reason: 'Not enabled on this deployment.',
    },
    {
      code: 'manual',
      label: 'Bank transfer',
      available: true,
      self_serve: false,
      unavailable_reason: null,
    },
  ],
  configuration: {
    country_code: 'US',
    country_name: 'United States',
    currency: 'USD',
    currency_symbol: '$',
    currency_decimal_places: 2,
    billing_model: 'Usage-based, billed monthly in arrears',
    invoice_cadence: 'Monthly',
    payment_terms_days: 21,
    free_monthly_allowance: { CONVERSATION: '100' },
    auto_suspend_enabled: true,
    suspend_after_days: 21,
    projection_strategy_default: 'rolling_7_day',
  },
  unit_prices: [
    {
      metric_code: 'BILLABLE_MESSAGE',
      display_name: 'Billable message',
      unit: 'message',
      unit_amount: '0.002000',
      currency: 'USD',
      source: 'company',
      effective_from: '2026-01-01T00:00:00Z',
      free_allowance: '100.000000',
      // A volume table: the rate above is the one this month's usage selects.
      tiers: [
        { up_to: '200.000000', unit_amount: '0.002000' },
        { up_to: '500.000000', unit_amount: '0.001500' },
        { up_to: null, unit_amount: '0.001000' },
      ],
    },
    {
      metric_code: 'AI_AUTOPILOT',
      display_name: 'AI Autopilot reply',
      unit: 'reply',
      unit_amount: null,
      currency: '',
      source: null,
      effective_from: null,
      free_allowance: '0.000000',
      tiers: [],
    },
  ],
  breakdowns: [
    {
      dimension: 'channel',
      rows: [
        ['whatsapp', 180],
        ['web_chat', 60],
      ],
      total: 240,
    },
    {
      dimension: 'origin',
      rows: [
        ['customer', 140],
        ['agent', 100],
      ],
      total: 240,
    },
  ],
  projection_alternatives: [DAILY_AVERAGE, LINEAR],
}

function mock({
  dashboard = DASHBOARD,
  estimate = ESTIMATE,
  onEstimate = () => {},
  onDashboard = () => {},
}: {
  dashboard?: BillingDashboard
  estimate?: BillingEstimate
  onEstimate?: (url: URL) => void
  onDashboard?: (url: URL) => void
} = {}) {
  // The page seeds its live figures from the dashboard response, exactly as
  // the API produces them together — so a fixture that changes the estimate
  // changes the one embedded in the dashboard too. Serving two different
  // estimates would test a state the server cannot produce.
  const embedded: BillingDashboard = { ...dashboard, estimate }
  server.use(
    http.get(`${API_BASE_URL}/billing/dashboard`, ({ request }) => {
      onDashboard(new URL(request.url))
      return HttpResponse.json(embedded)
    }),
    http.get(`${API_BASE_URL}/billing/estimate`, ({ request }) => {
      onEstimate(new URL(request.url))
      return HttpResponse.json(estimate)
    }),
    http.get(`${API_BASE_URL}/billing/daily`, ({ request }) => {
      const window = new URL(request.url).searchParams.get('window') ?? '30d'
      return HttpResponse.json({ ...embedded.daily, window })
    }),
    http.get(`${API_BASE_URL}/billing/invoices/:invoiceId`, () =>
      HttpResponse.json({
        invoice: embedded.invoices[0],
        lines: [
          {
            metric_code: 'CONVERSATION',
            description: 'Conversations (June 2026)',
            unit: 'conversation',
            quantity: '580.000000',
            included_quantity: '100.000000',
            billable_quantity: '480.000000',
            unit_amount: '0.050000',
            currency: 'USD',
            subtotal: '24.000000',
          },
        ],
      }),
    ),
  )
}

describe('BillingPage', () => {
  beforeEach(() => {
    // Cleared here rather than in afterEach: afterEach runs before RTL
    // unmounts, so a still-mounted observer refetches and repopulates the
    // previous test's data.
    queryClient.clear()
  })

  it('answers the five questions above the fold', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    // What I spent today, and this month.
    expect(await within(await screen.findByTestId('card-today')).findByText('$1.25')).toBeVisible()
    expect(within(screen.getByTestId('card-mtd')).getByText('$8.00')).toBeVisible()
    // What I am expected to pay, and how that was worked out.
    expect(within(screen.getByTestId('card-projection')).getByText('$31.00')).toBeVisible()
    expect(screen.getAllByText(/Rolling 7-Day Average/).length).toBeGreaterThan(0)
    // Whether I need to act.
    expect(screen.getByTestId('billing-status')).toHaveTextContent('Up to date')
    // What is generating my costs. Scoped to the period table: the same
    // metric appears under Today and again in the rate card.
    const table = within(screen.getByRole('table', { name: /This period/ }))
    expect(table.getByText('87.5%')).toBeVisible()
  })

  it('never shows a projection without its method', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    const card = within(await screen.findByTestId('projection-card'))
    expect(card.getByText(/Method: Rolling 7-Day Average/)).toBeVisible()
    expect(card.getByText(/average of the last 7 complete days/i)).toBeVisible()
  })

  it('says so when the projection fell back to another method', async () => {
    // Fewer than 7 complete days: the rolling average cannot run, and
    // claiming it did would be a small lie that costs a lot of trust.
    mock({ estimate: { ...ESTIMATE, projection: FELL_BACK } })
    renderAuthenticated(<BillingPage />)

    const card = within(await screen.findByTestId('projection-card'))
    expect(card.getByText(/Method: Current Daily Average/)).toBeVisible()
    expect(await screen.findByTestId('projection-fallback')).toHaveTextContent(
      /Rolling 7-Day Average needs 7 complete days/i,
    )
  })

  it('explains why there is no projection instead of showing zero', async () => {
    mock({
      estimate: {
        ...ESTIMATE,
        projection: {
          ...ROLLING,
          projected_total: null,
          daily_average: null,
          days_measured: 0,
          unavailable_reason: 'no_complete_days',
          unavailable_explanation:
            'This billing period has no complete day yet. A projection will appear tomorrow.',
        },
      },
    })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText(/no complete day yet/i)).toBeVisible()
    expect(
      within(screen.getByTestId('card-projection')).getByText('Not yet available'),
    ).toBeVisible()
  })

  it('offers the other strategies for comparison', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    const card = within(await screen.findByTestId('projection-card'))
    expect(card.getByText('Current Daily Average')).toBeVisible()
    expect(card.getByText('Linear Projection (current pace)')).toBeVisible()
    expect(card.getByText('$34.00')).toBeVisible()
  })

  it('asks the server for a different method rather than deriving one', async () => {
    const requested: string[] = []
    mock({
      estimate: { ...ESTIMATE, projection: LINEAR },
      onEstimate: (url) => requested.push(url.searchParams.get('strategy') ?? 'default'),
    })
    renderAuthenticated(<BillingPage />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('combobox', { name: /Projection method/i }))
    await user.click(await screen.findByRole('option', { name: /Linear Projection/i }))

    // A projection is only ever computed server-side: three strategies over
    // the same daily costs is arithmetic this page must not attempt.
    await waitFor(() => expect(requested).toContain('linear_pace'))
  })

  it('separates estimated charges from issued invoices', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByRole('heading', { name: 'Issued invoices' })).toBeVisible()
    expect(screen.getByText(/The invoices below are the official documents/i)).toBeVisible()
    expect(screen.getByText('INV-2026-000123')).toBeVisible()
    // "Estimated cost" heads the usage tables above the divider; the invoice
    // table below says "Total". The two are never the same word.
    expect(screen.getAllByText('Estimated cost').length).toBeGreaterThan(0)
  })

  it('loads invoice lines only when an invoice is expanded', async () => {
    let lineRequests = 0
    mock()
    server.use(
      http.get(`${API_BASE_URL}/billing/invoices/:invoiceId`, () => {
        lineRequests += 1
        return HttpResponse.json({
          invoice: DASHBOARD.invoices[0],
          lines: [
            {
              metric_code: 'CONVERSATION',
              description: 'Conversations (June 2026)',
              unit: 'conversation',
              quantity: '580.000000',
              included_quantity: '100.000000',
              billable_quantity: '480.000000',
              unit_amount: '0.050000',
              currency: 'USD',
              subtotal: '24.000000',
            },
          ],
        })
      }),
    )
    renderAuthenticated(<BillingPage />)

    await screen.findByText('INV-2026-000123')
    expect(lineRequests).toBe(0)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Show what invoice/i }))

    expect(await screen.findByText('Conversations (June 2026)')).toBeVisible()
    expect(lineRequests).toBe(1)
  })

  it('shows the free allowance, so a small bill is explainable', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    const table = within(await screen.findByRole('table', { name: /This period/ }))
    const row = within(table.getByRole('row', { name: /Conversation.*240/ }))
    expect(row.getByText('100')).toBeVisible()
    expect(row.getByText('140')).toBeVisible()
  })

  it('shows a rate a customer negotiated as theirs', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    const table = within(await screen.findByRole('table', { name: /Unit prices/i }))
    expect(table.getByText('Negotiated for you')).toBeVisible()
    // A metric with no rate is a gap, not a free metric.
    expect(table.getByText('No rate set')).toBeVisible()
  })

  it('offers only the payment methods this deployment can actually take', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText('Bank transfer')).toBeVisible()
    expect(screen.getByText('Not enabled on this deployment.')).toBeVisible()
    expect(screen.getByText('Unavailable')).toBeVisible()
  })

  it('re-reads only the chart when the window changes', async () => {
    const windows: string[] = []
    mock()
    server.use(
      http.get(`${API_BASE_URL}/billing/daily`, ({ request }) => {
        const window = new URL(request.url).searchParams.get('window') ?? '30d'
        windows.push(window)
        return HttpResponse.json({ ...DAILY, window })
      }),
    )
    renderAuthenticated(<BillingPage />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '7 days' }))

    await waitFor(() => expect(windows).toContain('7d'))
  })

  it('tells the customer the figures refresh by themselves', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByTestId('live-chip')).toHaveTextContent(/refreshes automatically/i)
  })

  it('polls the estimate without re-reading the whole page', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let dashboardRequests = 0
    let estimateRequests = 0
    server.use(
      http.get(`${API_BASE_URL}/billing/dashboard`, () => {
        dashboardRequests += 1
        return HttpResponse.json(DASHBOARD)
      }),
      http.get(`${API_BASE_URL}/billing/estimate`, () => {
        estimateRequests += 1
        return HttpResponse.json({ ...ESTIMATE, estimated_today: '2.500000' })
      }),
      http.get(`${API_BASE_URL}/billing/daily`, () => HttpResponse.json(DAILY)),
    )
    renderAuthenticated(<BillingPage />)

    await screen.findByTestId('card-today')
    // Seeded from the dashboard response, so the first paint is one request.
    expect(estimateRequests).toBe(0)

    await vi.advanceTimersByTimeAsync(46_000)

    await waitFor(() => expect(estimateRequests).toBeGreaterThan(0))
    // The expensive parts — invoices, pricing, payment configuration — are
    // not re-read on a timer.
    expect(dashboardRequests).toBe(1)
    expect(await within(screen.getByTestId('card-today')).findByText('$2.50')).toBeVisible()
    vi.useRealTimers()
  })

  it('says what to do in the customer’s own language, not the server’s', async () => {
    // The sentence is composed server-side so every surface says the same
    // thing; the code is what lets it be said in Arabic.
    mock({
      dashboard: {
        ...DASHBOARD,
        overview: {
          ...DASHBOARD.overview,
          billing_status: 'payment_overdue',
          status_detail: 'Payment is 4 day(s) overdue. Service will be suspended on 2026-08-12.',
          status_detail_code: 'overdue_with_suspension',
          status_detail_params: { days: 4, date: '2026-08-12' },
        },
      },
    })
    renderAuthenticated(<BillingPage />)

    const banner = await screen.findByTestId('billing-status')
    expect(banner).toHaveTextContent('Payment overdue')
    expect(banner).toHaveTextContent(
      'Payment is 4 day(s) overdue. Service will be suspended on 2026-08-12 if it remains unpaid.',
    )
  })

  it('falls back to the server sentence for a code it does not know', async () => {
    mock({
      dashboard: {
        ...DASHBOARD,
        overview: {
          ...DASHBOARD.overview,
          status_detail: 'Something new the API started saying.',
          // @ts-expect-error — deliberately a code this build has no
          // translation for: a newer server must not blank the banner.
          status_detail_code: 'a_code_from_the_future',
          status_detail_params: {},
        },
      },
    })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByTestId('billing-status')).toHaveTextContent(
      'Something new the API started saying.',
    )
  })

  it('shows where the messages came from, without pricing the channels', async () => {
    // Billing is channel-agnostic: a breakdown is volume, and a per-channel
    // cost would be a number the invoice does not contain.
    mock()
    renderAuthenticated(<BillingPage />)

    const mix = within(await screen.findByTestId('message-mix'))
    expect(mix.getByText('WhatsApp')).toBeVisible()
    expect(mix.getByText('180')).toBeVisible()
    expect(mix.getByText(/240 billable messages/)).toBeVisible()
    // No money anywhere in the card.
    expect(screen.getByTestId('message-mix').textContent).not.toMatch(/\$/)
  })

  it('lets a customer switch to who sent the messages', async () => {
    mock()
    renderAuthenticated(<BillingPage />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'By sender' }))

    const mix = within(screen.getByTestId('message-mix'))
    expect(mix.getByText('Customers')).toBeVisible()
    expect(mix.getByText('Agents')).toBeVisible()
  })

  it('shows the volume table behind a tiered rate', async () => {
    // "Why am I paying 0.002?" is answered by the table, not by the number.
    mock()
    renderAuthenticated(<BillingPage />)

    const table = within(await screen.findByRole('table', { name: /Unit prices/i }))
    expect(table.getByText(/Up to 200/)).toBeVisible()
    expect(table.getByText(/Above that/)).toBeVisible()
  })

  it('shows an empty state rather than zeros when no period is open', async () => {
    mock({
      dashboard: {
        ...DASHBOARD,
        overview: { ...DASHBOARD.overview, no_open_period: true },
      },
    })
    renderAuthenticated(<BillingPage />)

    expect(await screen.findByText(/No billing period is open/i)).toBeVisible()
  })

  it('renders a three-decimal currency at its own scale', async () => {
    // JOD is billed in fils. Rounding it to two places would misstate every
    // figure on the page.
    mock({
      dashboard: {
        ...DASHBOARD,
        overview: {
          ...DASHBOARD.overview,
          currency: 'JOD',
          currency_symbol: 'JD',
          currency_decimal_places: 3,
          estimated_month_to_date: '5.678000',
        },
        estimate: { ...ESTIMATE, currency: 'JOD', estimated_month_to_date: '5.678000' },
      },
      estimate: { ...ESTIMATE, currency: 'JOD', estimated_month_to_date: '5.678000' },
    })
    renderAuthenticated(<BillingPage />)

    expect(await within(await screen.findByTestId('card-mtd')).findByText(/5\.678/)).toBeVisible()
  })
})
