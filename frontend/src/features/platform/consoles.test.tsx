import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { App } from '../../App'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { authenticated, loggedOut } from '../auth/authSlice'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'

/**
 * The two operator consoles, and the line between them.
 *
 * Running the installation and running the revenue system are different jobs.
 * They share authority — a platform operator, outside tenant RBAC entirely —
 * so the risk in splitting them is not that a screen looks wrong, it is that
 * the new surface ends up reachable without the guard. That is what most of
 * this file is about.
 */

function goTo(path: string) {
  window.history.pushState({}, '', path)
}

function signedInAsOperator({ isPlatformAdmin = true }: { isPlatformAdmin?: boolean } = {}) {
  store.dispatch(
    authenticated({ accessToken: 'mock-access-token', refreshToken: 'mock-refresh-token' }),
  )
  server.use(
    http.get(`${API_BASE_URL}/platform/me`, () =>
      isPlatformAdmin
        ? HttpResponse.json({
            id: 'op-1',
            email: 'operator@blinkengage.io',
            name: 'Ada Lovelace',
            is_platform_admin: true,
            is_read_only: false,
          })
        : HttpResponse.json({ detail: 'Not a platform operator' }, { status: 403 }),
    ),
    http.get(`${API_BASE_URL}/platform/companies`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/effective`, () =>
      HttpResponse.json({
        resolved_at: '2026-07-30T12:00:00Z',
        company_id: null,
        profile_id: null,
        profile_name: null,
        currency: 'USD',
        items: [],
      }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/profiles`, () => HttpResponse.json([])),
    http.get(`${API_BASE_URL}/platform/pricing/health`, () =>
      HttpResponse.json({ ok: true, metrics: [] }),
    ),
    http.get(`${API_BASE_URL}/platform/pricing/history`, () => HttpResponse.json([])),
    http.get(`${API_BASE_URL}/platform/pricing/metrics`, () => HttpResponse.json([])),
    http.get(`${API_BASE_URL}/platform/pricing/models`, () => HttpResponse.json([])),
    http.get(`${API_BASE_URL}/platform/billing/revenue`, () =>
      HttpResponse.json({
        period_from: '2026-07-01',
        period_to: '2026-07-31',
        currencies: [],
        companies_behind: 0,
        companies_suspended: 0,
        as_of: '2026-07-31T12:00:00Z',
      }),
    ),
  )
}

describe('the operator consoles', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(() => {
    store.dispatch(loggedOut())
    goTo('/')
  })

  it('gives billing its own console rather than a tab beside companies', async () => {
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByText('Billing Console')).toBeVisible()
    expect(screen.getByText(/what things cost/i)).toBeVisible()
  })

  it('no longer offers pricing from the platform console', async () => {
    // The whole point of the split: an operator managing companies is not
    // shown the revenue system, and vice versa.
    signedInAsOperator()
    goTo('/platform')
    render(<App />)

    expect(await screen.findByText('Platform Console')).toBeVisible()
    const nav = screen.getByRole('navigation')
    expect(nav).not.toHaveTextContent(/pricing/i)
  })

  it('lets an operator cross from one console to the other', async () => {
    signedInAsOperator()
    goTo('/platform')
    render(<App />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('link', { name: 'Billing Console' }))

    expect(await screen.findByText(/what things cost/i)).toBeVisible()
    // …and back, so neither console is a dead end.
    await user.click(await screen.findByRole('link', { name: 'Platform Console' }))
    expect(await screen.findByText(/manage companies on this installation/i)).toBeVisible()
  })

  it('opens the billing console on the numbers rather than on a form', async () => {
    // A finance module's front page is what the business earned. A settings
    // page's front page is a rate editor — which is why pricing moved to its
    // own section rather than staying the console's index.
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Revenue' })).toBeVisible()
  })

  it('keeps a company’s billing workspace inside the billing console', async () => {
    // What "billing" means for one company: standing, what they owe, what
    // they have been invoiced. Their *pricing* is a different screen,
    // because setting a rate and chasing a debt are different jobs.
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/billing/companies/co-1/standing`, () =>
        HttpResponse.json({
          company_id: 'co-1',
          company_name: 'Acme Trading',
          currency: 'USD',
          billing_status: 'active',
          billing_suspended_at: null,
          never_auto_suspend: false,
          open_invoices: 0,
          overdue_invoices: 0,
          amount_outstanding: '0.000000',
          next_action_on: null,
        }),
      ),
      http.get(`${API_BASE_URL}/platform/billing/companies/co-1/invoices`, () =>
        HttpResponse.json([]),
      ),
      http.get(`${API_BASE_URL}/platform/billing/companies/co-1/dashboard`, () =>
        HttpResponse.json({ detail: 'not needed for this assertion' }, { status: 404 }),
      ),
    )
    goTo('/platform/billing/companies/co-1')
    render(<App />)

    expect(await screen.findByText('Billing Console')).toBeVisible()
    expect(await screen.findByRole('heading', { name: 'Acme Trading' })).toBeVisible()
  })

  it('still reaches per-company pricing, on its own path', async () => {
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/pricing/companies/co-1/effective`, () =>
        HttpResponse.json({
          resolved_at: '2026-07-30T12:00:00Z',
          company_id: 'co-1',
          profile_id: null,
          profile_name: null,
          currency: 'USD',
          items: [],
        }),
      ),
    )
    goTo('/platform/billing/pricing/companies/co-1')
    render(<App />)

    expect(await screen.findByText('Billing Console')).toBeVisible()
  })

  it('refuses the billing console to anyone without platform authority', async () => {
    // The reason the console is nested under `/platform` rather than mounted
    // at a new top-level path: it inherits the guard instead of needing to
    // remember one.
    signedInAsOperator({ isPlatformAdmin: false })
    goTo('/platform/billing')
    render(<App />)

    // Sent to their own workspace, not shown an error — they followed a link
    // that simply is not theirs.
    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(screen.queryByText('Billing Console')).not.toBeInTheDocument()
  })
})
