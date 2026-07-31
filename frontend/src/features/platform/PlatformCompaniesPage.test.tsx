import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { PlatformCompaniesPage } from './PlatformCompaniesPage'

const COMPANIES = [
  {
    id: 'co-1',
    name: 'Acme Support',
    slug: 'acme-support',
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    user_count: 12,
    agent_count: 8,
    conversation_count: 431,
  },
  {
    id: 'co-2',
    name: 'Globex Care',
    slug: 'globex-care',
    status: 'suspended',
    created_at: '2026-01-02T00:00:00Z',
    user_count: 3,
    agent_count: 2,
    conversation_count: 17,
  },
]

function mockCompanies(items = COMPANIES, { readOnly = false } = {}) {
  server.use(
    http.get(`${API_BASE_URL}/platform/companies`, () =>
      HttpResponse.json({ items, total: items.length, page: 1, page_size: 20 }),
    ),
    // Which kind of operator is looking, stated rather than left to a
    // default. The page defaults to read-only until this answers — it
    // will not offer a button before it knows the button is allowed — so
    // a test that omits this is testing the locked-down case whether it
    // meant to or not.
    http.get(`${API_BASE_URL}/platform/me`, () =>
      HttpResponse.json({
        id: 'op-1',
        email: 'operator@blinkengage.io',
        name: 'Ada Lovelace',
        is_platform_admin: true,
        read_only: readOnly,
      }),
    ),
  )
}

describe('PlatformCompaniesPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists every company with its lifecycle state and size', async () => {
    mockCompanies()
    renderAuthenticated(<PlatformCompaniesPage />)

    expect(await screen.findByText('Acme Support')).toBeInTheDocument()
    expect(screen.getByText('Globex Care')).toBeInTheDocument()
    expect(screen.getByText('431')).toBeInTheDocument()
  })

  it('never requests tenant data — only the platform API', async () => {
    // The product promise the platform tier is built around: platform
    // staff cannot read customers' conversations. Asserted on the
    // *requests made*, not on rendered text — the page legitimately says
    // words like "Conversations" (a count column) and "messages keep
    // arriving" (the suspension explainer), so matching on copy would
    // pass or fail for the wrong reasons.
    const requested: string[] = []
    server.events.on('request:start', ({ request }) => {
      requested.push(new URL(request.url).pathname)
    })
    mockCompanies()
    renderAuthenticated(<PlatformCompaniesPage />)
    await screen.findByText('Acme Support')

    const tenantPaths = requested.filter((path) =>
      /\/(conversations|customers|messages|agents)(\/|$)/.test(path),
    )
    expect(tenantPaths).toEqual([])
    expect(requested.some((path) => path.includes('/platform/companies'))).toBe(true)
  })

  it('offers Suspend on an active company and Reactivate on a suspended one', async () => {
    mockCompanies()
    renderAuthenticated(<PlatformCompaniesPage />)
    await screen.findByText('Acme Support')

    const active = screen.getByText('Acme Support').closest('[role="row"]') as HTMLElement
    const suspended = screen.getByText('Globex Care').closest('[role="row"]') as HTMLElement
    expect(within(active).getByRole('button', { name: /suspend/i })).toBeInTheDocument()
    expect(within(suspended).getByRole('button', { name: /reactivate/i })).toBeInTheDocument()
  })

  it('confirms before suspending, and says what suspension actually does', async () => {
    const user = userEvent.setup()
    mockCompanies()
    renderAuthenticated(<PlatformCompaniesPage />)
    await screen.findByText('Acme Support')

    const row = screen.getByText('Acme Support').closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('button', { name: /suspend/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/acme support/i)).toBeInTheDocument()
    // Two consequences an operator must know before clicking: people are
    // locked out immediately, and customer messages keep arriving.
    expect(within(dialog).getByText(/already signed in/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/messages keep arriving/i)).toBeInTheDocument()
  })

  it('sends the status change once confirmed', async () => {
    const user = userEvent.setup()
    let patched: { id?: string; status?: string } = {}
    mockCompanies()
    server.use(
      http.patch(
        `${API_BASE_URL}/platform/companies/:companyId/status`,
        async ({ params, request }) => {
          const body = (await request.json()) as { status: string }
          patched = { id: String(params.companyId), status: body.status }
          return HttpResponse.json({ ...COMPANIES[0], status: body.status })
        },
      ),
    )
    renderAuthenticated(<PlatformCompaniesPage />)
    await screen.findByText('Acme Support')

    const row = screen.getByText('Acme Support').closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('button', { name: /suspend/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^suspend$/i }))

    await waitFor(() => expect(patched).toEqual({ id: 'co-1', status: 'suspended' }))
  })

  it('surfaces a failed status change instead of silently doing nothing', async () => {
    const user = userEvent.setup()
    mockCompanies()
    server.use(
      http.patch(`${API_BASE_URL}/platform/companies/:companyId/status`, () =>
        HttpResponse.json({ detail: 'Company not found' }, { status: 404 }),
      ),
    )
    renderAuthenticated(<PlatformCompaniesPage />)
    await screen.findByText('Acme Support')

    const row = screen.getByText('Acme Support').closest('[role="row"]') as HTMLElement
    await user.click(within(row).getByRole('button', { name: /suspend/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^suspend$/i }))

    expect(await screen.findByText(/company not found/i)).toBeInTheDocument()
  })

  it('shows an empty state rather than a bare grid when nothing matches', async () => {
    mockCompanies([])
    renderAuthenticated(<PlatformCompaniesPage />)

    expect(await screen.findByText(/no companies/i)).toBeInTheDocument()
  })

  it('shows a retryable error when the list fails to load', async () => {
    server.use(
      http.get(`${API_BASE_URL}/platform/companies`, () =>
        HttpResponse.json({ detail: 'Boom' }, { status: 500 }),
      ),
    )
    renderAuthenticated(<PlatformCompaniesPage />)

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
