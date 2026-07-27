import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ConversationWorkspacePage } from './ConversationWorkspacePage'

function renderWorkspace() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationWorkspacePage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

// jsdom in this project doesn't implement matchMedia at all (confirmed —
// `window.matchMedia` is `undefined`), which MUI's `useMediaQuery` treats
// exactly like an SSR environment: it falls back to `defaultMatches`
// (`false`), i.e. every test file in this suite already implicitly runs
// in "mobile" mode by default. Stubbing it here is the only way to
// exercise the desktop (both-panes-visible) branch.
function stubDesktopViewport() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

describe('ConversationWorkspacePage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    // @ts-expect-error — restoring jsdom's real default (no matchMedia at
    // all), so this stub can't leak into any other test file.
    delete window.matchMedia
  })

  it('shows only the open conversation on mobile, without the list panel', async () => {
    renderWorkspace()
    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: /conversations/i })).not.toBeInTheDocument()
  })

  it('shows the conversation list alongside the open conversation on desktop', async () => {
    stubDesktopViewport()
    renderWorkspace()

    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: /conversations/i })).toBeInTheDocument()

    // "Grace Blake" (the seeded conversation's customer) legitimately
    // renders more than once once both panes are visible — once in the
    // list row, again in the detail pane's own header/sidebar.
    expect(await screen.findAllByText('Grace Blake')).not.toHaveLength(0)
  })

  it("the list panel's status quick-filter only shows conversations in that status", async () => {
    const user = userEvent.setup()
    stubDesktopViewport()
    renderWorkspace()
    await screen.findByLabelText(/^status/i)

    // The seeded conversation is "open" — switching the list panel's own
    // filter to "Pending" should hide it there (the detail pane on the
    // right is unaffected, still showing the same open conversation).
    await user.click(screen.getByRole('tab', { name: /^pending$/i }))
    expect(await screen.findByText(/nothing here/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations on desktop', async () => {
    stubDesktopViewport()
    const { container } = renderWorkspace()
    await screen.findByLabelText(/^status/i)
    expect(await axe(container)).toHaveNoViolations()
  })
})
