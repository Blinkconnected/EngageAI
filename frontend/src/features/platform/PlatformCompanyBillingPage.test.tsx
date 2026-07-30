import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { queryClient } from '../../app/queryClient'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { PlatformCompanyBillingPage } from './PlatformCompanyBillingPage'
import type { EffectivePrice } from './types'

const COMPANY_ID = '11111111-1111-1111-1111-111111111111'

const GLOBAL_PRICED: EffectivePrice = {
  metric_code: 'CONVERSATION',
  display_name: 'Conversation',
  unit: 'conversation' as const,
  unit_amount: '0.035000',
  currency: 'JOD',
  scope: 'global' as const,
  rate_id: 'rate-global',
  effective_from: '2026-01-01T00:00:00Z',
  effective_until: null,
  shadowed: [],
}

const OVERRIDDEN: EffectivePrice = {
  ...GLOBAL_PRICED,
  unit_amount: '0.028000',
  scope: 'company' as const,
  rate_id: 'rate-company',
  // What lost. An override that is itself overridden looks applied
  // unless the losing rates are visible.
  shadowed: [
    { scope: 'global' as const, unit_amount: '0.035000', rate_id: 'rate-global', profile_id: null },
  ],
}

const UNPRICED: EffectivePrice = {
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

function mock({
  items = [GLOBAL_PRICED, UNPRICED],
  readOnly = false,
  profileName = null as string | null,
  history = [] as unknown[],
} = {}) {
  server.use(
    http.get(`${API_BASE_URL}/platform/me`, () =>
      HttpResponse.json({
        id: 'op-1',
        email: 'ops@example.com',
        full_name: 'Ops',
        read_only: readOnly,
      }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/effective`, () =>
      HttpResponse.json({
        resolved_at: '2026-07-29T12:00:00Z',
        company_id: COMPANY_ID,
        profile_id: profileName ? 'profile-1' : null,
        profile_name: profileName,
        currency: 'JOD',
        items,
      }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/profiles`, () =>
      HttpResponse.json([
        {
          id: 'profile-1',
          key: 'enterprise',
          name: 'Enterprise',
          description: null,
          is_system: true,
          is_active: true,
          sort_order: 40,
        },
      ]),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/history`, () => HttpResponse.json(history)),
  )
}

/** Wrapped in its real route, because the page reads `companyId` from
 * the URL — rendering it bare would leave `useParams()` empty and every
 * request would ask about a company with no id. */
function render() {
  return renderAuthenticated(
    <Routes>
      <Route
        path="/platform/billing/companies/:companyId"
        element={<PlatformCompanyBillingPage />}
      />
    </Routes>,
    [`/platform/billing/companies/${COMPANY_ID}`],
  )
}

describe('PlatformCompanyBillingPage', () => {
  beforeEach(() => {
    // Cleared here, not in afterEach: afterEach runs before RTL unmounts,
    // so a still-mounted observer refetches and repopulates the previous
    // test's data.
    queryClient.clear()
  })

  it('shows where each price comes from, using the resolver’s own answer', async () => {
    mock()
    render()

    const row = within(await screen.findByRole('row', { name: /Conversation/i }))
    expect(row.getByText('0.035000 JOD')).toBeInTheDocument()
    expect(row.getByText('Global default')).toBeInTheDocument()
  })

  it('shows a metric with no price as a gap rather than as zero', async () => {
    mock()
    render()

    const row = within(await screen.findByRole('row', { name: /AI Autopilot/i }))
    expect(row.getByText('No price set')).toBeInTheDocument()
  })

  it('reveals the prices an override beat', async () => {
    mock({ items: [OVERRIDDEN] })
    render()

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /1 overridden/i }))

    expect(await screen.findByText(/Global default: 0\.035000 — overridden/)).toBeInTheDocument()
  })

  it('formats amounts in the company’s currency, at its own scale', async () => {
    // JOD has three decimal places. The page prints what the server sent
    // rather than re-formatting a parsed float, so 0.035000 stays exact.
    mock()
    render()

    expect(await screen.findByText(/billed in JOD/)).toBeInTheDocument()
  })

  it('sends the rate it is replacing, so a concurrent edit cannot be lost', async () => {
    const bodies: unknown[] = []
    mock({ items: [OVERRIDDEN] })
    server.use(
      http.put(
        `${API_BASE_URL}/platform/pricing/companies/:companyId/metrics/:metric`,
        async ({ request }) => {
          bodies.push(await request.json())
          return HttpResponse.json({ rate: {}, resolved: null }, { status: 201 })
        },
      ),
    )
    render()

    const user = userEvent.setup()
    await user.click((await screen.findAllByRole('button', { name: /set override/i }))[0])
    // Scoped to the dialog: the profile section has its own Reason field.
    const dialog = within(await screen.findByRole('dialog'))
    await user.clear(dialog.getByLabelText(/price per unit/i))
    await user.type(dialog.getByLabelText(/price per unit/i), '0.020000')
    await user.type(dialog.getByLabelText(/reason/i), 'Renegotiated')
    await user.click(dialog.getByRole('button', { name: /save price/i }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      unit_amount: '0.020000',
      reason: 'Renegotiated',
      currency: 'JOD',
      expected_current_rate_id: 'rate-company',
    })
  })

  it('says there was no override to replace when creating the first one', async () => {
    const bodies: unknown[] = []
    mock({ items: [GLOBAL_PRICED] })
    server.use(
      http.put(
        `${API_BASE_URL}/platform/pricing/companies/:companyId/metrics/:metric`,
        async ({ request }) => {
          bodies.push(await request.json())
          return HttpResponse.json({ rate: {}, resolved: null }, { status: 201 })
        },
      ),
    )
    render()

    const user = userEvent.setup()
    await user.click((await screen.findAllByRole('button', { name: /set override/i }))[0])
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText(/reason/i), 'First override')
    await user.click(dialog.getByRole('button', { name: /save price/i }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ expect_no_current_rate: true })
  })

  it('renders the resolver’s answer verbatim rather than deriving one', async () => {
    mock({ items: [GLOBAL_PRICED] })
    server.use(
      http.post(`${API_BASE_URL}/platform/pricing/resolve`, () =>
        HttpResponse.json({
          priced: [
            {
              company_id: COMPANY_ID,
              metric_code: 'CONVERSATION',
              occurred_at: '2026-07-29T12:00:00Z',
              // Deliberately different from the table above: the preview
              // must show what the resolver said, not what the page
              // could have worked out for itself.
              unit_amount: '0.019000',
              currency: 'JOD',
              scope: 'profile',
              rate_id: 'rate-profile',
              quantity: null,
              amount: null,
            },
          ],
          unpriced: [],
        }),
      ),
    )
    render()

    const user = userEvent.setup()
    await user.click(await screen.findByLabelText(/what’s charged|what's charged/i))
    await user.click(await screen.findByRole('option', { name: 'Conversation' }))
    await user.click(screen.getByRole('button', { name: /ask the engine/i }))

    expect(
      await screen.findByText(/0\.019000 JOD per conversation, from the Profile/),
    ).toBeInTheDocument()
  })

  it('shows the resolver’s reason when nothing is priced', async () => {
    mock({ items: [GLOBAL_PRICED] })
    server.use(
      http.post(`${API_BASE_URL}/platform/pricing/resolve`, () =>
        HttpResponse.json({
          priced: [],
          unpriced: [
            {
              company_id: COMPANY_ID,
              metric_code: 'CONVERSATION',
              occurred_at: '2020-01-01T00:00:00Z',
              reason: 'No price covers 2020-01-01T00:00:00+00:00',
            },
          ],
        }),
      ),
    )
    render()

    const user = userEvent.setup()
    await user.click(await screen.findByLabelText(/what’s charged|what's charged/i))
    await user.click(await screen.findByRole('option', { name: 'Conversation' }))
    await user.click(screen.getByRole('button', { name: /ask the engine/i }))

    expect(await screen.findByText(/No price covers 2020-01-01/)).toBeInTheDocument()
  })

  it('shows who changed a price, when it took effect, and why', async () => {
    mock({
      history: [
        {
          id: 'audit-1',
          action: 'pricing.company_rate_changed',
          scope: 'company',
          metric_code: 'CONVERSATION',
          company_id: COMPANY_ID,
          profile_id: null,
          old_unit_amount: '0.035000',
          new_unit_amount: '0.028000',
          currency: 'JOD',
          effective_from: '2026-08-01T00:00:00Z',
          changed_by_email: 'ops@example.com',
          changed_by_name: 'Ops',
          reason: 'Launch partner rate',
          occurred_at: '2026-07-29T10:00:00Z',
        },
      ],
    })
    render()

    expect(await screen.findByText('Launch partner rate')).toBeInTheDocument()
    expect(screen.getByText('ops@example.com')).toBeInTheDocument()
    expect(screen.getByText('0.028000 JOD')).toBeInTheDocument()
  })

  describe('read-only operators', () => {
    it('says so, and disables every control', async () => {
      mock({ readOnly: true, items: [GLOBAL_PRICED] })
      render()

      expect(await screen.findByText(/read-only access/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /set override/i })).toBeDisabled()
      expect(screen.getByRole('button', { name: /change profile/i })).toBeDisabled()
    })

    it('still shows the history and the preview', async () => {
      // The point of the tier: auditing what a customer is charged
      // without the authority to change it.
      mock({ readOnly: true, items: [GLOBAL_PRICED] })
      render()

      expect(await screen.findByText(/Change history/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /ask the engine/i })).toBeInTheDocument()
    })
  })
})
