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
    // Required for Meta channels: it is their App Secret, which they use
    // to sign every delivery. A generated value would let setup succeed
    // and then silently drop every incoming message.
    await user.type(screen.getByLabelText(/app secret/i), 'meta-app-secret')
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

  it('shows a health badge reflecting the last known connection status', async () => {
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')
    expect(screen.getByText('Healthy')).toBeInTheDocument()
  })

  it('tests a connection from the guided wizard before saving', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')

    await user.click(screen.getByRole('button', { name: /connect channel/i }))
    await user.type(await screen.findByLabelText(/display name/i), 'Support WhatsApp')
    await user.type(screen.getByLabelText(/phone number id/i), '123456')
    await user.type(screen.getByLabelText(/^access token/i), 'secret-token')
    await user.type(screen.getByLabelText(/verify token/i), 'my-verify-token')

    await user.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText(/connected successfully/i)).toBeInTheDocument()
  })

  it('tests the connection of an already-saved channel from the edit dialog', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    const row = (await screen.findByText('Support Telegram')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    await screen.findByRole('heading', { name: /edit support telegram/i })
    await user.click(screen.getByRole('button', { name: /test connection/i }))

    expect(await screen.findByText(/connected successfully/i)).toBeInTheDocument()
  })

  it('opens the connection logs for a channel', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    const row = (await screen.findByText('Support Telegram')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Connection logs'))

    expect(await screen.findByText(/connection logs — support telegram/i)).toBeInTheDocument()
    expect(screen.getByText('Channel connected')).toBeInTheDocument()
  })

  it('connects a Telegram channel with the guided bot token field', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')

    await user.click(screen.getByRole('button', { name: /connect channel/i }))
    // MUI's Select isn't a native <select>, so userEvent.selectOptions
    // doesn't work on it — open the popup and click the option instead.
    await user.click(screen.getByLabelText(/channel type/i))
    await user.click(await screen.findByRole('option', { name: 'Telegram' }))
    await user.type(await screen.findByLabelText(/display name/i), 'Second Bot')
    await user.type(screen.getByLabelText(/bot token/i), '123:abc-token')
    await user.click(screen.getByRole('button', { name: /^connect channel$/i }))

    expect(await screen.findByText(/channel connected/i)).toBeInTheDocument()
    // Telegram's webhook is registered automatically server-side — there's
    // no provider dashboard to paste a webhook URL/secret into, unlike
    // WhatsApp/Messenger/Instagram.
    expect(
      screen.getByText(/registered the webhook with your bot automatically/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/webhook url/i)).not.toBeInTheDocument()
  })

  it('connects an Email channel with optional IMAP fields', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')

    await user.click(screen.getByRole('button', { name: /connect channel/i }))
    await user.click(screen.getByLabelText(/channel type/i))
    await user.click(await screen.findByRole('option', { name: 'Email' }))
    await user.type(await screen.findByLabelText(/display name/i), 'Support Inbox')
    await user.type(screen.getByLabelText(/smtp host/i), 'smtp.example.com')

    // IMAP section is collapsed by default.
    expect(screen.queryByLabelText(/imap host/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('switch', { name: /also receive replies/i }))
    await user.type(screen.getByLabelText(/imap host/i), 'imap.example.com')

    await user.click(screen.getByRole('button', { name: /^connect channel$/i }))
    expect(await screen.findByText(/channel connected/i)).toBeInTheDocument()
  }, // section on top of the shared heavy DataGrid mount every test in this // the suite that types into two extra fields and toggles a Collapse // this sandbox's constrained (2-core) hardware — it's the one test in // This test alone exceeds the file's already-bumped 15s default under
  // file pays for. A local override here (not another global bump) keeps
  // the rest of the suite's timeout tight on ordinary CI hardware.
  30_000)

  it('connects a Web Chat channel with no credential fields required', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<ChannelsPage />)
    await screen.findByText('Support Telegram')

    await user.click(screen.getByRole('button', { name: /connect channel/i }))
    await user.click(screen.getByLabelText(/channel type/i))
    await user.click(await screen.findByRole('option', { name: 'Web Chat' }))
    await user.type(await screen.findByLabelText(/display name/i), 'Website Chat')
    expect(screen.getByText(/needs no external credentials/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^connect channel$/i }))
    expect(await screen.findByText(/channel connected/i)).toBeInTheDocument()
    expect(screen.getByText(/nothing further to configure/i)).toBeInTheDocument()
  })
})
