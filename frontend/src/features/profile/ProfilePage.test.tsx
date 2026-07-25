import { afterEach, describe, expect, it } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ProfilePage } from './ProfilePage'

function LoginStub() {
  const location = useLocation()
  const message = (location.state as { message?: string } | null)?.message
  return <div>Login page stub{message ? ` — ${message}` : ''}</div>
}

function renderProfilePage() {
  return renderAuthenticated(
    <Routes>
      <Route path="/profile" element={<ProfilePage />} />
      <Route path="/login" element={<LoginStub />} />
    </Routes>,
    ['/profile'],
  )
}

describe('ProfilePage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the current user details', async () => {
    renderProfilePage()
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('owner@example.com')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderProfilePage()
    await screen.findByText('Ada Lovelace')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('changes the password and redirects to login', async () => {
    const user = userEvent.setup()
    renderProfilePage()
    await screen.findByText('Ada Lovelace')

    await user.type(screen.getByLabelText(/current password/i), 'the-current-password-1')
    await user.type(screen.getByLabelText(/^new password/i), 'a-brand-new-password-9')
    await user.type(screen.getByLabelText(/confirm new password/i), 'a-brand-new-password-9')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    await waitFor(() => expect(screen.getByText(/login page stub/i)).toBeInTheDocument())
    expect(screen.getByText(/password changed/i)).toBeInTheDocument()
    expect(store.getState().auth.accessToken).toBeNull()
  })

  it('shows an error when the new passwords do not match', async () => {
    const user = userEvent.setup()
    renderProfilePage()
    await screen.findByText('Ada Lovelace')

    await user.type(screen.getByLabelText(/current password/i), 'the-current-password-1')
    await user.type(screen.getByLabelText(/^new password/i), 'a-brand-new-password-9')
    await user.type(screen.getByLabelText(/confirm new password/i), 'does-not-match-9')
    await user.click(screen.getByRole('button', { name: /change password/i }))

    expect(await screen.findByText(/do not match/i)).toBeInTheDocument()
    // Still on the profile page — nothing was submitted.
    expect(screen.queryByText(/login page stub/i)).not.toBeInTheDocument()
  })
})
