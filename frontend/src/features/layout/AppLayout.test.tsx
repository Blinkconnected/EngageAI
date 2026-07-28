import { afterEach, describe, expect, it, vi } from 'vitest'
import { onlineManager } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { apiClient } from '../../shared/api/client'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import i18n, { LANGUAGE_STORAGE_KEY } from '../../i18n'
import { AppLayout } from './AppLayout'

// `useCompanyLogoUrl` is stubbed (real exports kept via importOriginal) —
// jsdom's Blob doesn't implement `.stream()`, which MSW's Response
// construction needs for any blob-typed response, so the real fetch path
// can't run here. Same documented tooling gap and same
// mock-the-blob-fetch workaround as AttachmentList.test.tsx; the real
// fetch-and-render path is covered by live verification against the
// production Docker stack in an actual browser, not an automated test.
vi.mock('../company/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../company/api')>()
  return {
    ...actual,
    useCompanyLogoUrl: (logoKey: string | null | undefined) => ({
      data: logoKey ? 'blob:mock-logo-url' : undefined,
    }),
  }
})

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
    onlineManager.setOnline(true)
  })

  it('shows the company name in the header', async () => {
    renderLayout()
    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
  })

  it('shows an offline banner when connectivity is lost, then a brief reconnected message', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderLayout()
    await screen.findByText('Acme Corp')
    expect(screen.queryByText(/you're offline/i)).not.toBeInTheDocument()

    onlineManager.setOnline(false)
    expect(await screen.findByText(/you're offline/i)).toBeInTheDocument()

    onlineManager.setOnline(true)
    expect(await screen.findByText(/back online/i)).toBeInTheDocument()
    expect(screen.queryByText(/you're offline/i)).not.toBeInTheDocument()

    vi.advanceTimersByTime(5000)
    await waitFor(() => expect(screen.queryByText(/back online/i)).not.toBeInTheDocument())
    vi.useRealTimers()
  })

  it('shows no logo image by default', async () => {
    renderLayout()
    await screen.findByText('Acme Corp')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows the logo once the company sets one', async () => {
    renderLayout()
    await screen.findByText('Acme Corp')

    // The mocked useCompanyLogoUrl (see the vi.mock above) reacts to
    // `logo_key` becoming truthy exactly like the real hook would once
    // GET /company/logo resolves — this exercises AppLayout's own
    // rendering decision, not the blob-fetch itself.
    const formData = new FormData()
    formData.append('file', new File(['fake-png-bytes'], 'logo.png', { type: 'image/png' }))
    await apiClient.post('/company/logo', formData, { headers: { 'Content-Type': undefined } })
    await queryClient.invalidateQueries({ queryKey: ['company'] })

    const logo = await screen.findByRole('img', { name: /acme corp logo/i })
    expect(logo).toHaveAttribute('src', 'blob:mock-logo-url')
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

    it('has no detectable accessibility violations with the menu open', async () => {
      const user = userEvent.setup()
      renderLayout()
      await user.click(await screen.findByRole('button', { name: /account/i }))
      await screen.findByRole('button', { name: 'Online' })

      // Scoped to the popover's own root, not the whole document: this
      // test's route content is a bare placeholder <div> with no landmark
      // around it (a fixture artifact, not a real page), which axe's
      // unrelated "region" rule would otherwise flag. Popover (not Menu)
      // is what makes aria-required-children pass here: the availability
      // ToggleButtonGroup and user-info block are no longer direct
      // children of a role="menu" list.
      const popover = screen
        .getByRole('button', { name: 'Online' })
        .closest('[role="presentation"]')
      expect(popover).not.toBeNull()
      expect(await axe(popover as HTMLElement)).toHaveNoViolations()
    })
  })

  describe('language menu', () => {
    it('opens to show both supported languages', async () => {
      const user = userEvent.setup()
      renderLayout()

      await user.click(await screen.findByRole('button', { name: /language menu/i }))

      expect(await screen.findByRole('menuitem', { name: 'English' })).toBeInTheDocument()
      expect(screen.getByRole('menuitem', { name: 'Arabic' })).toBeInTheDocument()
    })

    it('actually switches the rendered language when Arabic is selected, unlike the old direction-only toggle', async () => {
      const user = userEvent.setup()
      renderLayout()

      await user.click(await screen.findByRole('button', { name: /language menu/i }))
      await user.click(await screen.findByRole('menuitem', { name: 'Arabic' }))

      await waitFor(() => expect(i18n.language).toBe('ar'))
    })

    it('switches direction to match the selected language', async () => {
      const user = userEvent.setup()
      renderLayout()

      await user.click(await screen.findByRole('button', { name: /language menu/i }))
      await user.click(await screen.findByRole('menuitem', { name: 'Arabic' }))

      await waitFor(() => expect(document.dir).toBe('rtl'))
    })

    it('persists the choice so it survives a reload', async () => {
      const user = userEvent.setup()
      renderLayout()

      await user.click(await screen.findByRole('button', { name: /language menu/i }))
      await user.click(await screen.findByRole('menuitem', { name: 'Arabic' }))

      await waitFor(() => expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('ar'))
    })

    it('has no detectable accessibility violations with the menu open', async () => {
      const user = userEvent.setup()
      renderLayout()
      await user.click(await screen.findByRole('button', { name: /language menu/i }))
      const englishOption = await screen.findByRole('menuitem', { name: 'English' })

      const popover = englishOption.closest('[role="presentation"]')
      expect(popover).not.toBeNull()
      expect(await axe(popover as HTMLElement)).toHaveNoViolations()
    })

    it("applies the company's default language on load when this browser hasn't chosen one", async () => {
      renderLayout()
      await screen.findByText('Acme Corp')

      await apiClient.patch('/company', { settings: { language: 'ar' } })
      await queryClient.invalidateQueries({ queryKey: ['company'] })

      await waitFor(() => expect(i18n.language).toBe('ar'))
    })

    it('does not let the company default override a manual choice already made in this browser', async () => {
      // Simulates a returning user who picked Arabic last session (the
      // localStorage key is already set before the company query ever
      // resolves) — useLanguageSync must not silently switch them back
      // to whatever the company's default happens to be.
      localStorage.setItem(LANGUAGE_STORAGE_KEY, 'ar')
      await i18n.changeLanguage('ar')
      renderLayout()
      await screen.findByText('Acme Corp')

      await apiClient.patch('/company', { settings: { language: 'en' } })
      await queryClient.invalidateQueries({ queryKey: ['company'] })

      // Give useLanguageSync's effect a chance to (wrongly) fire before
      // asserting it didn't.
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(i18n.language).toBe('ar')
    })
  })
})
