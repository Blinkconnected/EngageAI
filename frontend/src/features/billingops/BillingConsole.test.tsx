import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { App } from '../../App'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { authenticated, loggedOut } from '../auth/authSlice'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import i18n from '../../i18n'

/**
 * What the Billing Console is allowed to show a finance team.
 *
 * Three rules carry this file, and each exists because the obvious version of
 * a finance screen gets it subtly wrong:
 *
 * - **Nothing is summed across currencies.** Dollars and dinars, no
 *   conversion, no stored rate. A combined total is not an approximation, it
 *   is meaningless — so two currencies must stay two visibly separate blocks.
 * - **A run rate is not MRR**, and it says which it is. There are no
 *   subscriptions here; the figure is derived, and a derived number quoted
 *   without its derivation is one nobody can defend.
 * - **Raw translation keys never reach a screen**, in either language.
 */

function goTo(path: string) {
  window.history.pushState({}, '', path)
}

const OPERATOR = {
  id: 'op-1',
  email: 'operator@blinkengage.io',
  name: 'Ada Lovelace',
  is_platform_admin: true,
  is_read_only: false,
}

const TWO_CURRENCIES = {
  period_from: '2026-07-01',
  period_to: '2026-07-31',
  currencies: [
    {
      currency: 'USD',
      revenue: '1200.000000',
      outstanding: '300.000000',
      customer_credit: '0.000000',
      bad_debt: '0.000000',
      collected: '900.000000',
      collection_ratio: '0.750000',
      run_rate: {
        amount: '1200.000000',
        currency: 'USD',
        method: 'trailing_30_day',
        days_observed: 30,
        is_meaningful: true,
      },
    },
    {
      currency: 'JOD',
      revenue: '850.000000',
      outstanding: '0.000000',
      customer_credit: '0.000000',
      bad_debt: '0.000000',
      collected: '850.000000',
      collection_ratio: '1.000000',
      run_rate: {
        amount: '850.000000',
        currency: 'JOD',
        method: 'trailing_30_day',
        days_observed: 30,
        is_meaningful: true,
      },
    },
  ],
  companies_behind: 2,
  companies_suspended: 1,
  as_of: '2026-07-31T12:00:00Z',
}

function signedInAsOperator() {
  store.dispatch(
    authenticated({ accessToken: 'mock-access-token', refreshToken: 'mock-refresh-token' }),
  )
  server.use(
    http.get(`${API_BASE_URL}/platform/me`, () => HttpResponse.json(OPERATOR)),
    http.get(`${API_BASE_URL}/platform/companies`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`${API_BASE_URL}/platform/billing/revenue`, () => HttpResponse.json(TWO_CURRENCIES)),
  )
}

describe('the revenue dashboard', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(async () => {
    store.dispatch(loggedOut())
    goTo('/')
    await i18n.changeLanguage('en')
  })

  it('keeps two currencies as two separate sets of books', async () => {
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByText('Books in USD')).toBeVisible()
    expect(screen.getByText('Books in JOD')).toBeVisible()
  })

  it('shows no combined total across currencies', async () => {
    // The figures are 1,200 and 850. Their sum, 2,050, is a number that
    // means nothing — no exchange rate is stored anywhere on purpose — and
    // it must not appear anywhere on the page.
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Books in USD')

    expect(screen.queryByText(/2,050/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^total$/i)).not.toBeInTheDocument()
  })

  it('states how the run rate was derived, beside the number', async () => {
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Books in USD')

    expect(screen.getAllByText(/recognised over the last 30 days/i)).toHaveLength(2)
  })

  it('says when a rate was scaled from some other window', async () => {
    // A year of history scaled to a month is a real figure and a useful
    // one, but it is not the trailing thirty-day rate. Naming it so is the
    // exact misquote the method field exists to prevent.
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/billing/revenue`, () =>
        HttpResponse.json({
          ...TWO_CURRENCIES,
          currencies: [
            {
              ...TWO_CURRENCIES.currencies[0],
              run_rate: {
                amount: '400.000000',
                currency: 'USD',
                method: 'scaled_from_window',
                days_observed: 90,
                is_meaningful: true,
              },
            },
          ],
        }),
      ),
    )
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Books in USD')

    expect(screen.getByText(/scaled to 30 days from a 90-day window/i)).toBeVisible()
  })

  it('says so rather than guessing when there is too little history', async () => {
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/billing/revenue`, () =>
        HttpResponse.json({
          ...TWO_CURRENCIES,
          currencies: [
            {
              ...TWO_CURRENCIES.currencies[0],
              run_rate: {
                amount: '0.000000',
                currency: 'USD',
                method: 'insufficient_history',
                days_observed: 3,
                is_meaningful: false,
              },
            },
          ],
        }),
      ),
    )
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByText('Not enough history')).toBeVisible()
    expect(screen.getByText(/3 days is too short to scale from/i)).toBeVisible()
  })

  it('reports no ratio at all for a period that billed nothing', async () => {
    // `null`, not 0%. A ratio with no denominator is undefined, and 0% reads
    // as a collections failure in a month that simply had no billing.
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/billing/revenue`, () =>
        HttpResponse.json({
          ...TWO_CURRENCIES,
          currencies: [
            {
              ...TWO_CURRENCIES.currencies[0],
              revenue: '0.000000',
              collected: '0.000000',
              collection_ratio: null,
            },
          ],
        }),
      ),
    )
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Books in USD')

    expect(screen.getByText(/nothing to measure against/i)).toBeVisible()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('says when the figures were read rather than implying they are live', async () => {
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByText(/read at/i)).toBeVisible()
  })

  it('renders every amount at its own currency’s resolution', async () => {
    // The dinar has three decimal places and the dollar two. A console that
    // rounded both to two would be showing a dinar figure that is wrong.
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/billing/revenue`, () =>
        HttpResponse.json({
          ...TWO_CURRENCIES,
          currencies: [
            { ...TWO_CURRENCIES.currencies[1], revenue: '1.775000', collected: '1.775000' },
          ],
        }),
      ),
    )
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Books in JOD')

    expect(screen.getAllByText(/1\.775/).length).toBeGreaterThan(0)
  })
})

describe('the console navigation', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(async () => {
    store.dispatch(loggedOut())
    goTo('/')
    await i18n.changeLanguage('en')
  })

  it('offers every module a finance team needs', async () => {
    signedInAsOperator()
    goTo('/platform/billing')
    render(<App />)

    await screen.findByText('Billing Console')
    const nav = screen.getByRole('navigation')

    for (const section of ['Revenue', 'Invoices', 'Payments', 'Ledger', 'Collections', 'Pricing']) {
      expect(within(nav).getByRole('link', { name: section })).toBeVisible()
    }
  })

  it('reaches collections from the dashboard’s own standing figures', async () => {
    signedInAsOperator()
    server.use(
      http.get(`${API_BASE_URL}/platform/payments/collections/aging`, () =>
        HttpResponse.json({ as_of: '2026-07-31T12:00:00Z', currencies: [] }),
      ),
      http.get(`${API_BASE_URL}/platform/payments/collections/status`, () => HttpResponse.json([])),
    )
    goTo('/platform/billing')
    render(<App />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('link', { name: 'Open collections' }))

    expect(await screen.findByRole('heading', { name: 'Collections' })).toBeVisible()
  })
})

describe('the Arabic catalogue', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  afterEach(async () => {
    store.dispatch(loggedOut())
    goTo('/')
    await i18n.changeLanguage('en')
  })

  it('translates the dashboard rather than showing raw keys', async () => {
    // The rule the product owner set: a raw translation key must never be
    // visible in production. A missing key renders as `revenue.title`, and
    // a dot in the rendered text is the cheapest way to catch that.
    signedInAsOperator()
    await i18n.changeLanguage('ar')
    goTo('/platform/billing')
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'الإيرادات' })).toBeVisible()
    expect(screen.queryByText(/^revenue\./)).not.toBeInTheDocument()
    expect(screen.queryByText(/^billingOps\./)).not.toBeInTheDocument()
  })

  it('covers every key the English catalogue has', async () => {
    // Structural rather than a spot check: a section added to one catalogue
    // and forgotten in the other is exactly how a raw key reaches a screen.
    const en = i18n.getResourceBundle('en', 'billingOps')
    const ar = i18n.getResourceBundle('ar', 'billingOps')

    const paths = (node: unknown, prefix = ''): string[] =>
      typeof node === 'object' && node !== null
        ? Object.entries(node as Record<string, unknown>).flatMap(([key, value]) =>
            paths(value, prefix ? `${prefix}.${key}` : key),
          )
        : [prefix]

    // Arabic has extra plural forms (`_two`, `_few`, `_many`) that English
    // does not need, so the assertion runs one way only.
    const missing = paths(en).filter((key) => !paths(ar).includes(key))
    expect(missing).toEqual([])
  })
})
