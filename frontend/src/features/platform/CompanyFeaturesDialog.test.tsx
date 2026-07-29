import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { CompanyFeaturesDialog } from './CompanyFeaturesDialog'
import type { CompanyOverview } from './types'

const COMPANY: CompanyOverview = {
  id: 'co-1',
  name: 'Acme Support',
  slug: 'acme-support',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  user_count: 12,
  agent_count: 8,
  conversation_count: 431,
  plan_name: 'Business',
  subscription_status: 'active',
}

const FEATURES = [
  {
    key: 'ai',
    name: 'AI Engine',
    description: 'Reply suggestions and Autopilot',
    enabled: true,
    source: 'plan' as const,
  },
  {
    key: 'workflows',
    name: 'Workflow Engine',
    description: 'Automate actions',
    enabled: false,
    source: 'override' as const,
  },
]

function mockFeatures(features = FEATURES) {
  server.use(
    http.get(`${API_BASE_URL}/platform/companies/:companyId/features`, () =>
      HttpResponse.json(features),
    ),
  )
}

describe('CompanyFeaturesDialog', () => {
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
  })

  it('shows every feature with whether it is on', async () => {
    mockFeatures()
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)

    expect(await screen.findByRole('switch', { name: 'AI Engine' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Workflow Engine' })).not.toBeChecked()
  })

  it('says where each answer came from', async () => {
    // An operator fixes a plan-disabled feature differently from an
    // override-disabled one, so the source has to be visible.
    mockFeatures()
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)

    expect(await screen.findByText('From plan')).toBeInTheDocument()
    expect(screen.getByText('Set here')).toBeInTheDocument()
  })

  it('sends only the overrides, so untouched features keep following the plan', async () => {
    const user = userEvent.setup()
    let sent: Record<string, boolean> | null = null
    mockFeatures()
    server.use(
      http.put(`${API_BASE_URL}/platform/companies/:companyId/features`, async ({ request }) => {
        const body = (await request.json()) as { overrides: Record<string, boolean> }
        sent = body.overrides
        return HttpResponse.json(FEATURES)
      }),
    )
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)
    await screen.findByRole('switch', { name: 'AI Engine' })

    await user.click(screen.getByRole('button', { name: /^save$/i }))

    // `ai` follows the plan and must not be pinned by an override just
    // because the dialog was opened.
    await waitFor(() => expect(sent).toEqual({ workflows: false }))
  })

  it('writes an override when a feature is toggled', async () => {
    const user = userEvent.setup()
    let sent: Record<string, boolean> | null = null
    mockFeatures()
    server.use(
      http.put(`${API_BASE_URL}/platform/companies/:companyId/features`, async ({ request }) => {
        const body = (await request.json()) as { overrides: Record<string, boolean> }
        sent = body.overrides
        return HttpResponse.json(FEATURES)
      }),
    )
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)
    await user.click(await screen.findByRole('switch', { name: 'AI Engine' }))

    await user.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(sent).toEqual({ workflows: false, ai: false }))
  })

  it('can clear an override so the feature follows the plan again', async () => {
    // The reason this is a PUT and not a PATCH: with a merge there would
    // be no way to *remove* an override, only to flip it.
    const user = userEvent.setup()
    let sent: Record<string, boolean> | null = null
    mockFeatures()
    server.use(
      http.put(`${API_BASE_URL}/platform/companies/:companyId/features`, async ({ request }) => {
        const body = (await request.json()) as { overrides: Record<string, boolean> }
        sent = body.overrides
        return HttpResponse.json(FEATURES)
      }),
    )
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)
    await screen.findByRole('switch', { name: 'Workflow Engine' })

    await user.click(screen.getByRole('button', { name: /follow plan/i }))
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(sent).toEqual({}))
  })

  it('surfaces a failed save instead of silently closing', async () => {
    const user = userEvent.setup()
    mockFeatures()
    server.use(
      http.put(`${API_BASE_URL}/platform/companies/:companyId/features`, () =>
        HttpResponse.json({ detail: 'Feature not found' }, { status: 404 }),
      ),
    )
    renderAuthenticated(<CompanyFeaturesDialog company={COMPANY} onClose={() => {}} />)
    await screen.findByRole('switch', { name: 'AI Engine' })

    await user.click(screen.getByRole('button', { name: /^save$/i }))

    expect(await screen.findByText(/feature not found/i)).toBeInTheDocument()
  })
})
