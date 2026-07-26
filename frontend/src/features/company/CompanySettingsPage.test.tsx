import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { CompanySettingsPage } from './CompanySettingsPage'

function renderWithRoutes(initialEntry = '/settings/company/general') {
  return renderAuthenticated(
    <Routes>
      <Route path="/settings/company/:tab?" element={<CompanySettingsPage />} />
    </Routes>,
    [initialEntry],
  )
}

describe('CompanySettingsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('redirects to the general tab when no tab is given', async () => {
    renderWithRoutes('/settings/company/')
    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
  })

  it('shows the current company name and slug on the general tab', async () => {
    renderWithRoutes()
    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('acme-corp')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('saves a new company name', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    const nameField = await screen.findByDisplayValue('Acme Corp')

    await user.clear(nameField)
    await user.type(nameField, 'New Name Inc')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('does not show the ERP tab by default', async () => {
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')
    expect(screen.queryByRole('tab', { name: 'ERP' })).not.toBeInTheDocument()
  })

  it('enabling ERP on the general tab reveals the ERP tab', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')

    await user.click(screen.getByRole('switch', { name: /enable erp integration/i }))

    const erpTab = await screen.findByRole('tab', { name: 'ERP' })
    await user.click(erpTab)
    expect(await screen.findByLabelText(/erpnext site url/i)).toBeInTheDocument()
  })

  it('navigates between tabs and shows each panel', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')

    await user.click(screen.getByRole('tab', { name: 'Branding' }))
    expect(await screen.findByLabelText(/logo url/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Language' }))
    expect(await screen.findByLabelText(/default language/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Timezone' }))
    expect(await screen.findByRole('combobox', { name: /^timezone$/i })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Business Hours' }))
    expect(await screen.findByLabelText(/enable business hours/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Notifications' }))
    expect(await screen.findByText(/company-wide/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Messaging' }))
    expect(await screen.findByLabelText(/typing indicator/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Security' }))
    expect(await screen.findByLabelText(/minimum password length/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'AI' }))
    expect(await screen.findByLabelText(/enable ai engine features/i)).toBeInTheDocument()
  })

  it('saves a branding logo url', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/branding')

    const logoField = await screen.findByLabelText(/logo url/i)
    await user.type(logoField, 'https://cdn.example.com/logo.png')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Saved.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /remove logo/i })).toBeInTheDocument()
  })

  it('saves the default language', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/language')

    await user.click(await screen.findByLabelText(/default language/i))
    await user.click(await screen.findByRole('option', { name: 'Arabic' }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('saves business hours', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/business-hours')

    await user.click(await screen.findByLabelText(/enable business hours/i))
    expect(await screen.findByLabelText(/monday opens at/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('toggles a company-wide notification policy', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/notifications')

    const toggle = await screen.findByRole('switch', { name: /enable new conversation assigned/i })
    expect(toggle).toBeChecked()
    await user.click(toggle)

    await waitFor(() => expect(toggle).not.toBeChecked())
  })

  it('toggles the typing indicator', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/messaging')

    const toggle = await screen.findByLabelText(/typing indicator/i)
    expect(toggle).toBeChecked()
    await user.click(toggle)
    expect(toggle).not.toBeChecked()
  })

  it('rejects an out-of-range minimum password length', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/security')

    const field = await screen.findByLabelText(/minimum password length/i)
    await user.clear(field)
    await user.type(field, '5')

    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })

  it('saves a raised minimum password length', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/security')

    const field = await screen.findByLabelText(/minimum password length/i)
    await user.clear(field)
    await user.type(field, '16')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('toggles AI features off', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/ai')

    const toggle = await screen.findByLabelText(/enable ai engine features/i)
    expect(toggle).toBeChecked()
    await user.click(toggle)
    expect(toggle).not.toBeChecked()
  })
})
