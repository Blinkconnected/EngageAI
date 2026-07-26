import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { apiClient } from '../../shared/api/client'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { RequireErpEnabled } from './RequireErpEnabled'

function renderWithGuard(initialEntry = '/erp-configs') {
  return renderAuthenticated(
    <Routes>
      <Route
        path="/erp-configs"
        element={
          <RequireErpEnabled>
            <div>ERP config content</div>
          </RequireErpEnabled>
        }
      />
      <Route path="/403" element={<div>Forbidden</div>} />
    </Routes>,
    [initialEntry],
  )
}

describe('RequireErpEnabled', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('redirects to 403 when ERP is not enabled', async () => {
    renderWithGuard()
    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
  })

  it('renders the children when ERP is enabled', async () => {
    // A fresh render (not the same instance as the redirect test above,
    // which already navigated away to /403) — enabling ERP mid-flight on
    // an already-redirected page wouldn't navigate back on its own,
    // same as any other route guard.
    await apiClient.patch('/company', { settings: { erp: { enabled: true } } })
    renderWithGuard()
    expect(await screen.findByText('ERP config content')).toBeInTheDocument()
  })
})
