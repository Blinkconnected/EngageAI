import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ErpConfigSettingsPage } from './ErpConfigSettingsPage'

describe('ErpConfigSettingsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the connect form when no ERPNext connection exists yet', async () => {
    renderAuthenticated(<ErpConfigSettingsPage />)
    expect(await screen.findByLabelText(/erpnext site url/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<ErpConfigSettingsPage />)
    await screen.findByLabelText(/erpnext site url/i)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('connects and then disconnects ERPNext', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ErpConfigSettingsPage />)

    await user.type(await screen.findByLabelText(/erpnext site url/i), 'https://acme.erpnext.com')
    await user.type(screen.getByLabelText(/^api key/i), 'key-123')
    await user.type(screen.getByLabelText(/^api secret/i), 'secret-456')
    await user.click(screen.getByRole('button', { name: /connect erpnext/i }))

    expect(await screen.findByText('https://acme.erpnext.com')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^disconnect$/i }))
    await user.click(await screen.findByRole('button', { name: /yes, disconnect/i }))

    await waitFor(() =>
      expect(screen.queryByText('https://acme.erpnext.com')).not.toBeInTheDocument(),
    )
  })
})
