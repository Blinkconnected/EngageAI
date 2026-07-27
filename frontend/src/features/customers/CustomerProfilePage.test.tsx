import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { apiClient } from '../../shared/api/client'
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

  it('does not show an ERPNext tab when the company has not enabled ERP', async () => {
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })
    expect(screen.queryByRole('tab', { name: /erpnext/i })).not.toBeInTheDocument()
  })

  it('shows ERPNext records on the ERP tab once the company enables ERP', async () => {
    const user = userEvent.setup()
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })

    await apiClient.patch('/company', { settings: { erp: { enabled: true } } })
    await queryClient.invalidateQueries({ queryKey: ['company'] })

    await user.click(await screen.findByRole('tab', { name: /erpnext/i }))
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

  it('does not show a rating summary until the customer has at least one rating', async () => {
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })
    expect(screen.queryByText(/average, based on/i)).not.toBeInTheDocument()
  })

  it('adds an internal rating from the Internal rating tab and reflects it in the header summary', async () => {
    const user = userEvent.setup()
    renderProfile()
    await screen.findByRole('heading', { name: 'Grace Blake' })

    await user.click(screen.getByRole('tab', { name: /internal rating/i }))
    expect(await screen.findByText(/no internal ratings yet/i)).toBeInTheDocument()

    // MUI's Rating radio inputs are visually hidden with zero on-screen
    // size, which userEvent.click's pointer-visibility check rejects as
    // "not clickable" — fireEvent.click bypasses that check and dispatches
    // the click directly, same workaround this component's own icon
    // buttons don't need since they're regular visible buttons.
    const stars = screen.getAllByRole('radio', { name: /5 star/i })
    fireEvent.click(stars[0])
    await user.type(screen.getByPlaceholderText(/optional note/i), 'Great customer')
    await user.click(screen.getByRole('button', { name: /add rating/i }))

    await waitFor(() => expect(screen.getByText('Great customer')).toBeInTheDocument())
    expect(screen.getByText(/5 average, based on 1 internal ratings/i)).toBeInTheDocument()
  })
})
