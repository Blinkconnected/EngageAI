import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { RolesPage } from './RolesPage'

describe('RolesPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists the seeded system roles', async () => {
    renderAuthenticated(<RolesPage />)
    expect(await screen.findByText('Owner')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()
    expect(screen.getByText('Agent')).toBeInTheDocument()
    expect(screen.getAllByText('System')).toHaveLength(3)
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<RolesPage />)
    await screen.findByText('Owner')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('creates a new role with selected permissions', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<RolesPage />)
    await screen.findByText('Owner')

    await user.click(screen.getByRole('button', { name: /new role/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Billing Reviewer')
    await user.click(await screen.findByRole('checkbox', { name: /view reports and dashboards/i }))
    await user.click(screen.getByRole('button', { name: /create role/i }))

    expect(await screen.findByText('Billing Reviewer')).toBeInTheDocument()
    const row = (await screen.findByText('Billing Reviewer')).closest('tr') as HTMLElement
    expect(within(row).getByText('Custom')).toBeInTheDocument()
    expect(within(row).getByText('1')).toBeInTheDocument()
  })

  it('edits a custom role name, description, and permissions', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<RolesPage />)
    await screen.findByText('Owner')

    await user.click(screen.getByRole('button', { name: /new role/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Tier 1')
    await user.click(screen.getByRole('button', { name: /create role/i }))
    await screen.findByText('Tier 1')

    const row = (await screen.findByText('Tier 1')).closest('tr') as HTMLElement
    await user.click(within(row).getByLabelText(/^edit tier 1$/i))

    const nameField = await screen.findByLabelText(/^name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Tier 1 Support')
    await user.click(screen.getByRole('checkbox', { name: /view conversations/i }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Tier 1 Support')).toBeInTheDocument())
  })

  it('cannot rename a system role or change the Owner role permissions', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<RolesPage />)
    const row = (await screen.findByText('Owner')).closest('tr') as HTMLElement

    await user.click(within(row).getByLabelText(/^edit owner$/i))
    const nameField = await screen.findByLabelText(/^name/i)
    expect(nameField).toBeDisabled()
    expect(screen.getByText(/owner role always has every permission/i)).toBeInTheDocument()
  })

  it('disables deleting system roles and roles that still have members', async () => {
    renderAuthenticated(<RolesPage />)
    const ownerRow = (await screen.findByText('Owner')).closest('tr') as HTMLElement
    expect(within(ownerRow).getByLabelText(/^delete owner$/i)).toBeDisabled()

    const adminRow = screen.getByText('Admin').closest('tr') as HTMLElement
    expect(within(adminRow).getByLabelText(/^delete admin$/i)).toBeDisabled()
  })

  it('deletes an empty custom role after confirming', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<RolesPage />)
    await screen.findByText('Owner')

    await user.click(screen.getByRole('button', { name: /new role/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Unused')
    await user.click(screen.getByRole('button', { name: /create role/i }))
    await screen.findByText('Unused')

    const row = screen.getByText('Unused').closest('tr') as HTMLElement
    const deleteButton = within(row).getByLabelText(/^delete unused$/i)
    expect(deleteButton).not.toBeDisabled()
    await user.click(deleteButton)
    await user.click(await screen.findByRole('button', { name: /^remove$/i }))

    await waitFor(() => expect(screen.queryByText('Unused')).not.toBeInTheDocument())
  })

  it('shows the members of a role', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<RolesPage />)
    const row = (await screen.findByText('Agent')).closest('tr') as HTMLElement

    await user.click(within(row).getByLabelText(/view agent members/i))

    expect(await screen.findByText('Grace Hopper')).toBeInTheDocument()
    expect(screen.getByText('grace@example.com')).toBeInTheDocument()
  })
})
