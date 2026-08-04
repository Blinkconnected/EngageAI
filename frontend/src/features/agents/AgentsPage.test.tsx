import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { AgentsPage } from './AgentsPage'

describe('AgentsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists existing agents', async () => {
    renderAuthenticated(<AgentsPage />)
    expect(await screen.findByText('Grace Hopper')).toBeInTheDocument()
    expect(screen.getByText('grace@example.com')).toBeInTheDocument()
    expect(screen.getByText('Support')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<AgentsPage />)
    await screen.findByText('Grace Hopper')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('invites a new agent by email without the admin inventing a password', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    await screen.findByText('Grace Hopper')

    await user.click(screen.getByRole('button', { name: /new agent/i }))
    await user.type(await screen.findByLabelText(/full name/i), 'Ada Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'ada@example.com')

    // No password field by default. The API has always generated one and
    // emailed it; this dialog used to require the administrator to invent a
    // password and then transmit it out of band, for every agent they added.
    expect(screen.queryByLabelText(/initial password/i)).not.toBeInTheDocument()
    expect(screen.getByText(/we'll email this person/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /create agent/i }))

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('ada@example.com')).toBeInTheDocument()
  })

  it('still allows setting a password directly when that is wanted', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    await screen.findByText('Grace Hopper')

    await user.click(screen.getByRole('button', { name: /new agent/i }))
    await user.type(await screen.findByLabelText(/full name/i), 'Ada Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'ada@example.com')
    await user.click(screen.getByLabelText(/set a password myself/i))
    await user.type(await screen.findByLabelText(/initial password/i), 'correct-horse-1')
    await user.click(screen.getByRole('button', { name: /create agent/i }))

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
  })

  it('edits an agent title', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    const row = (await screen.findByText('Grace Hopper')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    const titleField = await screen.findByLabelText(/title/i)
    await user.clear(titleField)
    await user.type(titleField, 'Principal Agent')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Principal Agent')).toBeInTheDocument())
  })

  it('resets an agent password through the dialog', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    const row = (await screen.findByText('Grace Hopper')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Reset password'))
    expect(await screen.findByText(/reset password for grace hopper/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/new password/i), 'a-reset-password-9')
    await user.click(screen.getByRole('button', { name: /^reset password$/i }))

    await waitFor(() =>
      expect(screen.queryByText(/reset password for grace hopper/i)).not.toBeInTheDocument(),
    )
  })

  it("changes an agent's role", async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    const row = (await screen.findByText('Grace Hopper')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Change role'))
    expect(await screen.findByText(/change grace hopper's role/i)).toBeInTheDocument()
    const roleField = await screen.findByLabelText(/^role/i)
    expect(roleField).toHaveTextContent('Agent')

    await user.click(roleField)
    await user.click(await screen.findByRole('option', { name: 'Admin' }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() =>
      expect(screen.queryByText(/change grace hopper's role/i)).not.toBeInTheDocument(),
    )

    await user.click(within(row as HTMLElement).getByLabelText('Change role'))
    expect(await screen.findByLabelText(/^role/i)).toHaveTextContent('Admin')
  })

  it('removes an agent by transferring their conversations to another agent', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    const row = (await screen.findByText('Grace Hopper')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Delete'))
    // Transfer is the default mode — pick a target agent to continue.
    await user.click(await screen.findByLabelText(/transfer to/i))
    await user.click(await screen.findByRole('option', { name: 'Mock Self Agent' }))
    await user.click(screen.getByRole('button', { name: /^continue$/i }))
    await user.click(await screen.findByRole('button', { name: /transfer & remove/i }))

    await waitFor(() => expect(screen.queryByText('Grace Hopper')).not.toBeInTheDocument())
  })

  it('permanently removes an agent after two confirmation steps', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AgentsPage />)
    const row = (await screen.findByText('Grace Hopper')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Delete'))
    await user.click(await screen.findByRole('button', { name: /^permanently delete$/i }))
    // First confirmation step: the consequences warning.
    await user.click(screen.getByRole('button', { name: /^continue$/i }))
    // Second confirmation step: the final button stays disabled until the
    // agent's exact name is typed in.
    await user.click(await screen.findByRole('button', { name: /^continue$/i }))
    const finalButton = await screen.findByRole('button', { name: /^permanently delete$/i })
    expect(finalButton).toBeDisabled()
    await user.type(screen.getByLabelText(/agent's full name/i), 'Grace Hopper')
    expect(finalButton).toBeEnabled()
    await user.click(finalButton)

    await waitFor(() => expect(screen.queryByText('Grace Hopper')).not.toBeInTheDocument())
  })
})
