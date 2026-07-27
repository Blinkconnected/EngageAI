import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { apiClient } from '../../shared/api/client'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { AppLayout } from './AppLayout'

function renderLayout(initialEntry = '/') {
  return renderAuthenticated(
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<div>Dashboard content</div>} />
        <Route path="onboarding" element={<div>Onboarding wizard content</div>} />
      </Route>
    </Routes>,
    [initialEntry],
  )
}

describe('AppLayout', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the company name in the header', async () => {
    renderLayout()
    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
  })

  it('shows no logo image by default', async () => {
    renderLayout()
    await screen.findByText('Acme Corp')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows the logo once the company sets one', async () => {
    renderLayout()
    await screen.findByText('Acme Corp')

    await apiClient.patch('/company', {
      settings: { branding: { logo_url: 'https://cdn.example.com/logo.png' } },
    })
    await queryClient.invalidateQueries({ queryKey: ['company'] })

    const logo = await screen.findByRole('img', { name: /acme corp logo/i })
    expect(logo).toHaveAttribute('src', 'https://cdn.example.com/logo.png')
  })

  it('shows a "Complete setup" banner when onboarding is incomplete', async () => {
    renderLayout()
    expect(await screen.findByText(/complete setup/i)).toBeInTheDocument()
  })

  it('hides the banner once onboarding is completed', async () => {
    renderLayout()
    await screen.findByText(/complete setup/i)

    await apiClient.patch('/company', { settings: { onboarding: { completed: true } } })
    await queryClient.invalidateQueries({ queryKey: ['company'] })

    await waitFor(() => expect(screen.queryByText(/complete setup/i)).not.toBeInTheDocument())
  })

  it('hides the banner while already on the onboarding page', async () => {
    renderLayout('/onboarding')
    await screen.findByText('Onboarding wizard content')
    expect(screen.queryByText(/complete setup/i)).not.toBeInTheDocument()
  })

  it('navigates to the wizard when the banner link is clicked', async () => {
    const user = userEvent.setup()
    renderLayout()

    await user.click(await screen.findByRole('link', { name: /complete setup/i }))
    await waitFor(() => expect(screen.getByText('Onboarding wizard content')).toBeInTheDocument())
  })

  describe('account menu availability picker', () => {
    async function openAccountMenu(user: ReturnType<typeof userEvent.setup>) {
      renderLayout()
      await user.click(await screen.findByRole('button', { name: /account/i }))
      return screen.findByRole('button', { name: 'Online' })
    }

    it("highlights the agent's current status", async () => {
      const user = userEvent.setup()
      const onlineButton = await openAccountMenu(user)
      // Matches the "Mock Self Agent" seed's status (agents.ts) — proves
      // the picker actually reads the caller's own agent record rather
      // than always defaulting to the first option.
      expect(onlineButton).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Away' })).toHaveAttribute('aria-pressed', 'false')
    })

    it('round-trips a status change through PATCH /agents/me/status', async () => {
      const user = userEvent.setup()
      await openAccountMenu(user)

      await user.click(screen.getByRole('button', { name: 'Busy' }))

      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Busy' })).toHaveAttribute(
          'aria-pressed',
          'true',
        ),
      )
      expect(screen.getByRole('button', { name: 'Online' })).toHaveAttribute(
        'aria-pressed',
        'false',
      )
    })

    // No open-menu axe pass here (unlike InboxPage/ConversationSidebar's
    // new controls, which do get one): this account Menu already renders
    // non-`menuitem` content as direct children of its `role="menu"` list
    // (the currentUser name/email/roles Box, present before this change) —
    // opening it and running axe flags `aria-required-children` on that
    // pre-existing structure, not on anything this milestone added.
    // Restructuring the account menu's ARIA semantics to satisfy that rule
    // is out of scope here. This matches this codebase's existing
    // precedent of only axe-checking Menu-owning components in their
    // closed state (see NotificationBell.test.tsx).
  })
})
