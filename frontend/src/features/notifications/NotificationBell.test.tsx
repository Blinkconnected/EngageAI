import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { NotificationBell } from './NotificationBell'

describe('NotificationBell', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the unread count badge', async () => {
    renderAuthenticated(<NotificationBell />)
    expect(await screen.findByLabelText(/notifications \(1 unread\)/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<NotificationBell />)
    await screen.findByLabelText(/notifications \(1 unread\)/i)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('opens the menu and marks all as read', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<NotificationBell />)

    await user.click(await screen.findByLabelText(/notifications \(1 unread\)/i))
    expect(await screen.findByText('New conversation assigned')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /mark all read/i }))

    await waitFor(() => expect(screen.getByLabelText(/^notifications$/i)).toBeInTheDocument())
  })
})
