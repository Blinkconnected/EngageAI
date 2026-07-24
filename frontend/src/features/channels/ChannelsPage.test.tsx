import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ChannelsPage } from './ChannelsPage'

describe('ChannelsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists existing channels', async () => {
    renderAuthenticated(<ChannelsPage />)
    expect(await screen.findByText('Support Telegram')).toBeInTheDocument()
    expect(screen.getByText('Telegram')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('connects a WhatsApp channel and shows webhook setup instructions', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')

    await user.click(screen.getByRole('button', { name: /connect channel/i }))
    // Channel type defaults to WhatsApp, so its fields are already shown.
    await user.type(await screen.findByLabelText(/display name/i), 'Support WhatsApp')
    await user.type(screen.getByLabelText(/phone number id/i), '123456')
    await user.type(screen.getByLabelText(/^access token/i), 'secret-token')
    await user.type(screen.getByLabelText(/verify token/i), 'my-verify-token')
    await user.click(screen.getByRole('button', { name: /^connect channel$/i }))

    expect(await screen.findByText(/channel connected/i)).toBeInTheDocument()
    expect(screen.getByDisplayValue(/\/api\/v1\/webhooks\//)).toBeInTheDocument()
    expect(screen.getByDisplayValue('my-verify-token')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^done$/i }))
    expect(await screen.findByText('Support WhatsApp')).toBeInTheDocument()
  })

  it('edits a channel display name', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    const row = (await screen.findByText('Support Telegram')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    const nameField = await screen.findByLabelText(/display name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Renamed Telegram')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Renamed Telegram')).toBeInTheDocument())
  })

  it('disconnects a channel after confirming', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    const row = (await screen.findByText('Support Telegram')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Delete'))
    await user.click(await screen.findByRole('button', { name: /^disconnect$/i }))

    await waitFor(() => expect(screen.queryByText('Support Telegram')).not.toBeInTheDocument())
  })
})
