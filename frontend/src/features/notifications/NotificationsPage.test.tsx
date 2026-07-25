import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { apiClient } from '../../shared/api/client'
import { NotificationsPage } from './NotificationsPage'

describe('NotificationsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('defaults to the History tab, listing notifications', async () => {
    renderAuthenticated(<NotificationsPage />)
    expect(await screen.findByText('New conversation assigned')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /history/i, selected: true })).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('"Unread only" hides read notifications', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')

    await user.click(screen.getByRole('button', { name: /mark all read/i }))
    await user.click(screen.getByRole('switch', { name: /unread only/i }))

    await waitFor(() => expect(screen.getByText(/no notifications/i)).toBeInTheDocument())
  })

  it('deletes a notification', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')

    await user.click(screen.getByRole('button', { name: /delete notification/i }))

    await waitFor(() =>
      expect(screen.queryByText('New conversation assigned')).not.toBeInTheDocument(),
    )
  })

  it('switches to the Preferences tab and shows the toggle matrix', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')

    await user.click(screen.getByRole('tab', { name: /preferences/i }))

    expect(await screen.findByRole('table', { name: /notification preferences/i })).toBeInTheDocument()
    const table = screen.getByRole('table', { name: /notification preferences/i })
    expect(within(table).getByText('New conversation assigned')).toBeInTheDocument()
    expect(within(table).getAllByRole('switch').every((el) => (el as HTMLInputElement).checked)).toBe(
      true,
    )
  })

  it('toggling a preference switch off persists it', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')
    await user.click(screen.getByRole('tab', { name: /preferences/i }))

    const table = await screen.findByRole('table', { name: /notification preferences/i })
    const emailToggle = within(table).getByRole('switch', {
      name: /new conversation assigned via email/i,
    })
    expect((emailToggle as HTMLInputElement).checked).toBe(true)

    await user.click(emailToggle)

    await waitFor(() => expect((emailToggle as HTMLInputElement).checked).toBe(false))
  })

  it('re-enabling the browser channel (it starts on by default) requests permission first', async () => {
    const requestPermission = vi.fn().mockResolvedValue('granted')
    vi.stubGlobal(
      'Notification',
      Object.assign(vi.fn(), { permission: 'default', requestPermission }),
    )

    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')
    await user.click(screen.getByRole('tab', { name: /preferences/i }))

    const table = await screen.findByRole('table', { name: /notification preferences/i })
    const browserToggle = within(table).getByRole('switch', {
      name: /new conversation assigned via browser/i,
    })
    // Preferences default to enabled, so the first click turns it *off*
    // (no permission needed to disable something).
    await user.click(browserToggle)
    await waitFor(() => expect((browserToggle as HTMLInputElement).checked).toBe(false))
    expect(requestPermission).not.toHaveBeenCalled()

    // Turning it back on is the realistic "opt in" moment that must
    // request browser permission first.
    await user.click(browserToggle)

    await waitFor(() => expect(requestPermission).toHaveBeenCalledTimes(1))
    await waitFor(() => expect((browserToggle as HTMLInputElement).checked).toBe(true))
  })

  it('does not persist "enabled" when the browser denies the permission request', async () => {
    const requestPermission = vi.fn().mockResolvedValue('denied')
    vi.stubGlobal(
      'Notification',
      Object.assign(vi.fn(), { permission: 'default', requestPermission }),
    )
    // Spies on the real axios call (the actual regression this guards
    // against is "a second PUT fires despite the denial") while still
    // letting the request reach the mock's real, state-persisting
    // handler — unlike overriding the MSW handler itself, which would
    // bypass that persistence and desync the switch from "server" state.
    const putSpy = vi.spyOn(apiClient, 'put')

    const user = userEvent.setup()
    renderAuthenticated(<NotificationsPage />)
    await screen.findByText('New conversation assigned')
    await user.click(screen.getByRole('tab', { name: /preferences/i }))

    const table = await screen.findByRole('table', { name: /notification preferences/i })
    const browserToggle = within(table).getByRole('switch', {
      name: /new conversation assigned via browser/i,
    })
    await user.click(browserToggle) // off (no permission needed)
    await waitFor(() => expect(putSpy).toHaveBeenCalledTimes(1))

    await user.click(browserToggle) // attempt to re-enable — permission will be denied

    await waitFor(() => expect(requestPermission).toHaveBeenCalledTimes(1))
    // Denied: the switch must not flip to checked, and — the actual
    // regression this guards against — no second PUT (re-enabling) may
    // have been issued at all.
    expect((browserToggle as HTMLInputElement).checked).toBe(false)
    expect(putSpy).toHaveBeenCalledTimes(1)
  })
})
