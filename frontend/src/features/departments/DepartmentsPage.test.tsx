import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { DepartmentsPage } from './DepartmentsPage'

describe('DepartmentsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists existing departments', async () => {
    renderAuthenticated(<DepartmentsPage />)
    expect(await screen.findByText('Support')).toBeInTheDocument()
    expect(screen.getByText('Sales')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<DepartmentsPage />)
    await screen.findByText('Support')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('creates a new department through the dialog', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<DepartmentsPage />)
    await screen.findByText('Support')

    await user.click(screen.getByRole('button', { name: /new department/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Billing')
    await user.click(screen.getByRole('button', { name: /create department/i }))

    expect(await screen.findByText('Billing')).toBeInTheDocument()
  })

  it('edits a department name and active status', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<DepartmentsPage />)
    const row = (await screen.findByText('Support')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    const nameField = await screen.findByLabelText(/^name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Customer Support')
    await user.click(screen.getByRole('switch', { name: /active/i }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Customer Support')).toBeInTheDocument())
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('deletes a department after confirming', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<DepartmentsPage />)
    const row = (await screen.findByText('Sales')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Delete'))
    await user.click(await screen.findByRole('button', { name: /^remove$/i }))

    await waitFor(() => expect(screen.queryByText('Sales')).not.toBeInTheDocument())
  })

  it('shows assigned agents when the agent count chip is clicked', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<DepartmentsPage />)
    await screen.findByText('Support')

    await user.click(screen.getByText('1'))
    expect(await screen.findByText('Support — Agents')).toBeInTheDocument()
    expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
  })
})
