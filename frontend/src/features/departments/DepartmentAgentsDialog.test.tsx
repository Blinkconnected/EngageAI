import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { DepartmentAgentsDialog } from './DepartmentAgentsDialog'
import type { Department } from './types'

const DEPARTMENT: Department = {
  id: 'd1',
  name: 'Support',
  description: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('DepartmentAgentsDialog', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows a retryable error instead of a false "no agents" empty state when the agents fetch fails', async () => {
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    server.use(
      http.get(`${API_BASE_URL}/agents`, () =>
        HttpResponse.json({ message: 'boom' }, { status: 500 }),
      ),
    )

    renderAuthenticated(<DepartmentAgentsDialog department={DEPARTMENT} onClose={() => {}} />)

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.queryByText(/no agents assigned/i)).not.toBeInTheDocument()
  })

  it('shows a loading state before the agents list resolves', () => {
    renderAuthenticated(<DepartmentAgentsDialog department={DEPARTMENT} onClose={() => {}} />)

    expect(screen.getByText(/loading agents/i)).toBeInTheDocument()
  })

  it('shows the empty state once loaded with no members, not while pending', async () => {
    const empty: Department = { ...DEPARTMENT, id: 'd-empty', name: 'Empty Dept' }
    renderAuthenticated(<DepartmentAgentsDialog department={empty} onClose={() => {}} />)

    expect(screen.getByText(/loading agents/i)).toBeInTheDocument()
    expect(await screen.findByText(/no agents assigned/i)).toBeInTheDocument()
  })
})
