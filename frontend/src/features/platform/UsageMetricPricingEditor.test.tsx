import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { queryClient } from '../../app/queryClient'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { UsageMetricPricingEditor } from './UsageMetricPricingEditor'
import type { BillableMetric, EffectivePrice, PricingModelInfo } from './types'

const MODELS: PricingModelInfo[] = [
  {
    model: 'flat',
    display_name: 'Flat rate',
    description: 'One rate for every unit.',
    enabled: true,
    implemented: true,
    requires_tiers: false,
  },
  {
    model: 'volume_tier',
    display_name: 'Volume tiers',
    description: "The period's total picks one rate.",
    enabled: true,
    implemented: true,
    requires_tiers: true,
  },
  {
    model: 'graduated_tier',
    display_name: 'Graduated tiers',
    description: 'Each bracket at its own rate.',
    enabled: false,
    implemented: true,
    requires_tiers: true,
  },
]

const METRIC: BillableMetric = {
  code: 'BILLABLE_MESSAGE',
  display_name: 'Billable message',
  unit: 'message',
  description: 'A customer-facing message on any channel.',
  kind: 'counter',
  availability: 'measured',
  is_priceable: true,
}

const PRICE: EffectivePrice = {
  metric_code: 'BILLABLE_MESSAGE',
  display_name: 'Billable message',
  unit: 'message',
  unit_amount: '0.002000',
  currency: 'USD',
  scope: 'global',
  rate_id: 'rate-1',
  effective_from: '2026-01-01T00:00:00Z',
  effective_until: null,
  shadowed: [],
}

function mock({
  onQuote = () => {},
  onSave = () => {},
  quoteStatus = 200,
  saveStatus = 201,
  saveDetail = 'flat pricing does not use a tier table.',
}: {
  onQuote?: (body: Record<string, unknown>) => void
  onSave?: (body: Record<string, unknown>) => void
  quoteStatus?: number
  saveStatus?: number
  saveDetail?: string
} = {}) {
  server.use(
    http.post(`${API_BASE_URL}/platform/pricing/quote`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      onQuote(body)
      if (quoteStatus !== 200) {
        return HttpResponse.json({ detail: 'Tier bounds must ascend.' }, { status: quoteStatus })
      }
      return HttpResponse.json({
        model: body.pricing_model,
        quantity: '300.000000',
        included_quantity: '100.000000',
        billable_quantity: '200.000000',
        unit_amount: '0.001500',
        tier_up_to: '500.000000',
        tier_index: 2,
        subtotal: '0.300000',
        currency: 'USD',
        minimum_applied: false,
      })
    }),
    http.put(
      `${API_BASE_URL}/platform/pricing/global/metrics/:metric`,
      async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        onSave(body)
        if (saveStatus !== 201) {
          return HttpResponse.json({ detail: saveDetail }, { status: saveStatus })
        }
        return HttpResponse.json({ rate: {}, resolved: null }, { status: 201 })
      },
    ),
  )
}

function render(onClose = () => {}) {
  return renderAuthenticated(
    <UsageMetricPricingEditor
      price={PRICE}
      metric={METRIC}
      models={MODELS}
      currency="USD"
      profileId={undefined}
      onClose={onClose}
    />,
  )
}

describe('UsageMetricPricingEditor', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('prices any metric, not messages specifically', async () => {
    // Everything on the screen comes from what the server said the metric and
    // the models are — so a token or a phone-minute meter prices here with no
    // change to this component.
    mock()
    render()

    expect(await screen.findByText(/Pricing for Billable message/)).toBeVisible()
    expect(screen.getByLabelText(/Rate per message/)).toHaveValue('0.002000')
  })

  it('offers the models the server enabled and shows the rest as coming', async () => {
    mock()
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Pricing model/i }))

    expect(await screen.findByRole('option', { name: /Flat rate/ })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    )
    // Declared, implemented, not yet offered: visible so an operator can see
    // what is coming, disabled so they cannot configure a price that would
    // never charge.
    expect(screen.getByRole('option', { name: /Graduated tiers/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('asks the server what the terms would charge, and never computes it', async () => {
    // The rule this screen exists to keep: a tier table applied in TypeScript
    // would eventually disagree with the invoice.
    const quotes: Record<string, unknown>[] = []
    mock({ onQuote: (body) => quotes.push(body) })
    render()

    await waitFor(() => expect(quotes.length).toBeGreaterThan(0))
    const preview = within(await screen.findByTestId('pricing-preview'))
    expect(await preview.findByText('0.300000 USD')).toBeVisible()
    expect(preview.getByText(/100.000000 included, 200.000000 chargeable/)).toBeVisible()

    expect(quotes[0]).toMatchObject({
      metric_code: 'BILLABLE_MESSAGE',
      currency: 'USD',
      quantity: '300',
      pricing_model: 'flat',
    })
  })

  it('shows the tier editor only for a model that needs one', async () => {
    mock()
    render()

    expect(screen.queryByRole('table', { name: /Tier table/i })).not.toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Pricing model/i }))
    await user.click(await screen.findByRole('option', { name: /Volume tiers/ }))

    expect(await screen.findByRole('table', { name: /Tier table/i })).toBeVisible()
  })

  it('seeds a tier table with the rate the metric already had', async () => {
    // Switching model changes the shape, never the price — otherwise picking
    // "tiered" would quietly reprice the metric.
    mock()
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Pricing model/i }))
    await user.click(await screen.findByRole('option', { name: /Volume tiers/ }))

    const table = within(await screen.findByRole('table', { name: /Tier table/i }))
    expect(table.getByLabelText(/^Rate$/)).toHaveValue('0.002000')
    expect(table.getByText(/and above/)).toBeVisible()
  })

  it('keeps the last step open-ended and undeletable', async () => {
    // A table whose top step ends somewhere leaves a customer past it with no
    // price. Enforced by the shape of the editor, not by a message after the
    // fact.
    mock()
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Pricing model/i }))
    await user.click(await screen.findByRole('option', { name: /Volume tiers/ }))
    await user.click(await screen.findByRole('button', { name: /Add a step/i }))

    const table = within(screen.getByRole('table', { name: /Tier table/i }))
    // Two steps: one bounded (deletable), one open-ended (not).
    expect(table.getAllByRole('button', { name: /Remove step/i })).toHaveLength(1)
    expect(table.getAllByText(/and above/)).toHaveLength(1)
  })

  it('sends the whole terms on save, not just an amount', async () => {
    const saved: Record<string, unknown>[] = []
    mock({ onSave: (body) => saved.push(body) })
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: /Pricing model/i }))
    await user.click(await screen.findByRole('option', { name: /Volume tiers/ }))
    await user.type(screen.getByLabelText(/Included free/i), '100')
    await user.type(screen.getByLabelText(/Minimum charge/i), '5')
    await user.click(screen.getByRole('button', { name: /Save price/i }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0]).toMatchObject({
      pricing_model: 'volume_tier',
      included_quantity: '100',
      minimum_charge: '5',
      tiers: [{ up_to: null, unit_amount: '0.002000' }],
      // Optimistic concurrency: the rate being replaced, so a second
      // operator's edit is refused rather than silently overwritten.
      expected_current_rate_id: 'rate-1',
    })
  })

  it('leaves the allowance unset when the operator does not set one', async () => {
    // Omitting means "the metric's own default"; sending 0 would mean "none",
    // which is a different price.
    const saved: Record<string, unknown>[] = []
    mock({ onSave: (body) => saved.push(body) })
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Save price/i }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0]).not.toHaveProperty('included_quantity')
    expect(saved[0]).not.toHaveProperty('minimum_charge')
  })

  it('shows the server’s refusal while typing rather than on save', async () => {
    mock({ quoteStatus: 422 })
    render()

    expect(await screen.findByText(/Tier bounds must ascend/)).toBeVisible()
  })

  it('surfaces a save failure with the server’s reason', async () => {
    mock({ saveStatus: 422, saveDetail: 'volume_tier pricing needs a tier table.' })
    render()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Save price/i }))

    expect(await screen.findByText(/needs a tier table/)).toBeVisible()
  })

  it('closes on a successful save', async () => {
    let closed = false
    mock()
    render(() => {
      closed = true
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Save price/i }))

    await waitFor(() => expect(closed).toBe(true))
  })
})
