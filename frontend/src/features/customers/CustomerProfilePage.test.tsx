import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { CustomerProfilePage } from './CustomerProfilePage'

function renderProfile() {
  return renderAuthenticated(
    <Routes>
      <Route path="/customers/:customerId" element={<CustomerProfilePage />} />
    </Routes>,
    ['/customers/cust-1'],
  )
}

describe('CustomerProfilePage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the customer name and their conversation in the timeline', async () => {
    renderProfile()
    expect(await screen.findByRole('heading', { name: 'Grace Blake' })).toBeInTheDocument()
    expect(await screen.findByText('Support Telegram')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })
    expect(await axe(container)).toHaveNoViolations()
  })

  it('shows ERPNext records on the ERP tab', async () => {
    const user = userEvent.setup()
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })

    await user.click(screen.getByRole('tab', { name: /erpnext/i }))
    expect(await screen.findByText('SINV-0001')).toBeInTheDocument()
    expect(screen.getByText('Sales Invoice')).toBeInTheDocument()
  })

  it('edits the customer', async () => {
    const user = userEvent.setup()
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })

    await user.click(screen.getByRole('button', { name: /^edit$/i }))
    const nameField = await screen.findByLabelText(/full name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Grace Renamed')
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Grace Renamed' })).toBeInTheDocument(),
    )
  })
})
