import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { CompanySettingsPage } from './CompanySettingsPage'

describe('CompanySettingsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the current company name and slug', async () => {
    renderAuthenticated(<CompanySettingsPage />)
    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('acme-corp')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<CompanySettingsPage />)
    await screen.findByDisplayValue('Acme Corp')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('saves a new company name', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<CompanySettingsPage />)
    const nameField = await screen.findByDisplayValue('Acme Corp')

    await user.clear(nameField)
    await user.type(nameField, 'New Name Inc')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })
})
