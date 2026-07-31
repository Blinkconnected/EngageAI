import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import i18n from '../../i18n'
import { loggedOut } from '../auth/authSlice'
import { setDirection } from '../ui/uiSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import enPlatform from '../../locales/en/platform.json'
import arPlatform from '../../locales/ar/platform.json'
import { CompanyUsersPage } from './CompanyUsersPage'
import type { CompanyUser } from './companyUsersApi'

const COMPANY_ID = '11111111-1111-1111-1111-111111111111'

const COMPANY = {
  id: COMPANY_ID,
  name: 'Acme Support',
  slug: 'acme-support',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  user_count: 3,
  agent_count: 2,
  conversation_count: 41,
}

const OWNER: CompanyUser = {
  id: 'user-owner',
  email: 'ada@acme.test',
  full_name: 'Ada Lovelace',
  is_active: true,
  is_company_owner: true,
  email_verified: true,
  last_login_at: '2026-07-20T09:30:00Z',
  created_at: '2026-01-01T00:00:00Z',
  role: { id: 'role-owner', name: 'Owner' },
}

const AGENT: CompanyUser = {
  id: 'user-agent',
  email: 'grace@acme.test',
  full_name: 'Grace Hopper',
  is_active: true,
  is_company_owner: false,
  email_verified: false,
  last_login_at: null,
  created_at: '2026-02-01T00:00:00Z',
  role: { id: 'role-agent', name: 'Agent' },
}

const DEACTIVATED: CompanyUser = {
  id: 'user-admin',
  email: 'alan@acme.test',
  full_name: 'Alan Turing',
  is_active: false,
  is_company_owner: false,
  email_verified: true,
  last_login_at: '2026-05-04T11:00:00Z',
  created_at: '2026-03-01T00:00:00Z',
  role: { id: 'role-admin', name: 'Admin' },
}

const USERS = [OWNER, AGENT, DEACTIVATED]

function mock({ users = USERS, readOnly = false } = {}) {
  server.use(
    http.get(`${API_BASE_URL}/platform/me`, () =>
      HttpResponse.json({
        id: 'op-1',
        email: 'ops@example.com',
        full_name: 'Ops',
        is_platform_admin: true,
        read_only: readOnly,
      }),
    ),
    http.get(`${API_BASE_URL}/platform/companies/${COMPANY_ID}`, () => HttpResponse.json(COMPANY)),
    http.get(`${API_BASE_URL}/platform/companies/${COMPANY_ID}/users`, () =>
      HttpResponse.json({ items: users, total: users.length }),
    ),
  )
}

/** Wrapped in its real route: the page reads `companyId` from the URL, so
 * rendering it bare would ask the API about a company with no id. */
function render() {
  return renderAuthenticated(
    <Routes>
      <Route path="/platform/companies/:companyId/users" element={<CompanyUsersPage />} />
    </Routes>,
    [`/platform/companies/${COMPANY_ID}/users`],
  )
}

/** Every leaf key of a translation bundle, as a dotted path. */
function keyPaths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) return [prefix]
  return Object.entries(value as Record<string, unknown>).flatMap(([key, nested]) =>
    keyPaths(nested, prefix ? `${prefix}.${key}` : key),
  )
}

describe('CompanyUsersPage', () => {
  beforeEach(() => {
    // Cleared here rather than in afterEach: afterEach runs before RTL
    // unmounts, so a still-mounted observer refetches and repopulates the
    // previous test's data.
    queryClient.clear()
  })

  afterEach(() => {
    store.dispatch(loggedOut())
    // The direction the Arabic test sets persists to localStorage, which
    // jsdom shares across every test in this file.
    store.dispatch(setDirection('ltr'))
  })

  it("lists the company's people and the state of each account", async () => {
    mock()
    render()

    expect(await screen.findByText('People at Acme Support')).toBeInTheDocument()

    const owner = within(screen.getByText('Ada Lovelace').closest('tr') as HTMLElement)
    expect(owner.getByText('ada@acme.test')).toBeInTheDocument()
    expect(owner.getByText('Owner', { selector: '.MuiChip-label' })).toBeInTheDocument()
    expect(owner.getByText('Active')).toBeInTheDocument()
    expect(owner.getByText('Verified')).toBeInTheDocument()

    const agent = within(screen.getByText('Grace Hopper').closest('tr') as HTMLElement)
    expect(agent.getByText('Not verified')).toBeInTheDocument()
    // Somebody who has never signed in is a different fact from somebody
    // whose last sign-in is unknown, and only one of them is true here.
    expect(agent.getByText('Never')).toBeInTheDocument()

    const deactivated = within(screen.getByText('Alan Turing').closest('tr') as HTMLElement)
    expect(deactivated.getByText('Deactivated')).toBeInTheDocument()
  })

  it('asks for a reason in the same step as the confirmation, and sends it', async () => {
    const user = userEvent.setup()
    const requests: { url: string; body: unknown }[] = []
    mock()
    server.use(
      http.patch(
        `${API_BASE_URL}/platform/companies/:companyId/users/:userId/status`,
        async ({ request }) => {
          requests.push({ url: new URL(request.url).pathname, body: await request.json() })
          return HttpResponse.json({ ...AGENT, is_active: false })
        },
      ),
    )
    render()

    await user.click(await screen.findByRole('button', { name: /deactivate grace hopper/i }))
    const dialog = within(await screen.findByRole('dialog'))
    // The consequence is stated before the action, not after it.
    expect(dialog.getByText(/until somebody reactivates the account/i)).toBeInTheDocument()
    await user.type(dialog.getByLabelText(/reason/i), 'Customer asked us to lock the account')
    await user.click(dialog.getByRole('button', { name: /^deactivate$/i }))

    await waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0].url).toContain('/platform/companies/')
    expect(requests[0].url).toContain('/users/user-agent/status')
    expect(requests[0].body).toEqual({
      is_active: false,
      reason: 'Customer asked us to lock the account',
    })
  })

  it('will not send a write with no reason', async () => {
    const user = userEvent.setup()
    const requests: unknown[] = []
    mock()
    server.use(
      http.patch(`${API_BASE_URL}/platform/companies/:companyId/users/:userId/status`, async () => {
        requests.push(true)
        return HttpResponse.json(AGENT)
      }),
    )
    render()

    await user.click(await screen.findByRole('button', { name: /deactivate grace hopper/i }))
    const dialog = within(await screen.findByRole('dialog'))
    const confirm = dialog.getByRole('button', { name: /^deactivate$/i })
    expect(confirm).toBeDisabled()

    // Whitespace is not a reason: the customer reads this sentence.
    await user.type(dialog.getByLabelText(/reason/i), '   ')
    expect(confirm).toBeDisabled()
    expect(requests).toEqual([])
  })

  it('offers no password-reset action, because the product has no reset flow', async () => {
    // The action was built, and its own test mocked the endpoint into
    // existence — so it passed while the button posted to a route that
    // does not exist. A console that says "a reset link has been sent"
    // when nothing was sent is worse than one that offers nothing: the
    // operator stops chasing a user who is still locked out.
    mock()
    render()

    await screen.findByText('Ada Lovelace')

    expect(screen.queryByRole('button', { name: /reset/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/reset link/i)).not.toBeInTheDocument()
  })
  it('sends the role it was asked to set', async () => {
    const user = userEvent.setup()
    const bodies: unknown[] = []
    mock()
    server.use(
      http.put(
        `${API_BASE_URL}/platform/companies/:companyId/users/:userId/role`,
        async ({ request }) => {
          bodies.push(await request.json())
          return HttpResponse.json({ ...AGENT, role: { id: 'role-admin', name: 'Admin' } })
        },
      ),
    )
    render()

    await user.click(await screen.findByRole('button', { name: /change grace hopper's role/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByLabelText(/new role/i))
    await user.click(await screen.findByRole('option', { name: 'Admin' }))
    await user.type(within(dialog).getByLabelText(/reason/i), 'Promoted at the customer’s request')
    await user.click(within(dialog).getByRole('button', { name: /change role/i }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      role_id: 'role-admin',
      reason: 'Promoted at the customer’s request',
    })
  })

  it('transfers ownership to the person chosen', async () => {
    const user = userEvent.setup()
    const bodies: unknown[] = []
    mock()
    server.use(
      http.post(`${API_BASE_URL}/platform/companies/:companyId/owner`, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ ...AGENT, is_company_owner: true })
      }),
    )
    render()

    await user.click(await screen.findByRole('button', { name: /make grace hopper the owner/i }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText(/reason/i), 'Founder left the company')
    await user.click(dialog.getByRole('button', { name: /transfer ownership/i }))

    await waitFor(() =>
      expect(bodies).toEqual([{ user_id: 'user-agent', reason: 'Founder left the company' }]),
    )
  })

  it('will not let the last owner be deactivated, and says why', async () => {
    const user = userEvent.setup()
    mock()
    render()

    // Disabled rather than allowed-then-refused: a company with no owner
    // has nobody who can manage its own roles, and finding that out from
    // a 409 teaches the operator nothing.
    const deactivate = await screen.findByRole('button', { name: /deactivate ada lovelace/i })
    expect(deactivate).toBeDisabled()

    await user.hover(deactivate.parentElement as HTMLElement)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      /last owner cannot be deactivated/i,
    )
  })

  it('does not offer to re-verify an address that is already verified', async () => {
    mock()
    render()

    expect(
      await screen.findByRole('button', { name: /resend the verification email to grace/i }),
    ).toBeEnabled()
    expect(
      screen.getByRole('button', { name: /resend the verification email to ada/i }),
    ).toBeDisabled()
  })

  it('shows a read-only operator the list and no actions at all', async () => {
    mock({ readOnly: true })
    render()

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText(/read-only access/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /deactivate/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /password-reset/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /owner/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Actions' })).not.toBeInTheDocument()
  })

  it('offers no way to assume an account, and reads no tenant data', async () => {
    // The boundary this screen sits on: an operator may restore access and
    // remove it, never assume it. Asserted on the controls offered and on
    // the requests made — the two ways it could actually be crossed.
    const requested: string[] = []
    server.events.on('request:start', ({ request }) => {
      requested.push(new URL(request.url).pathname)
    })
    mock()
    render()
    await screen.findByText('Ada Lovelace')

    expect(
      screen.queryByRole('button', { name: /sign in as|impersonate|set password|delete/i }),
    ).not.toBeInTheDocument()
    expect(
      requested.filter((path) => /\/(conversations|customers|messages)(\/|$)/.test(path)),
    ).toEqual([])
  })

  it('surfaces a refused write instead of silently doing nothing', async () => {
    const user = userEvent.setup()
    mock()
    server.use(
      http.patch(`${API_BASE_URL}/platform/companies/:companyId/users/:userId/status`, () =>
        HttpResponse.json({ detail: 'This user is the last owner' }, { status: 409 }),
      ),
    )
    render()

    await user.click(await screen.findByRole('button', { name: /deactivate grace hopper/i }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.type(dialog.getByLabelText(/reason/i), 'Offboarding')
    await user.click(dialog.getByRole('button', { name: /^deactivate$/i }))

    expect(await screen.findByText(/this user is the last owner/i)).toBeInTheDocument()
  })

  it('renders in Arabic, right to left', async () => {
    mock()
    store.dispatch(setDirection('rtl'))
    await i18n.changeLanguage('ar')
    render()

    // A section nested under the wrong parent still has every key the
    // parity test below looks for, and still puts "CompanyUsersPage.title"
    // on screen — so one Arabic string is read back off the rendered page.
    expect(await screen.findByText('الأشخاص في Acme Support')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'إيقاف Grace Hopper' })).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('dir', 'rtl')
  })

  it('has every English key translated into Arabic', () => {
    // A raw translation key on screen is a bug in either language, and the
    // console is the one surface an operator cannot work around.
    expect(keyPaths(arPlatform).sort()).toEqual(keyPaths(enPlatform).sort())
  })
})
