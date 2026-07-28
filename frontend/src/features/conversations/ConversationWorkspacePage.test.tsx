import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
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

// A real matchMedia stub, evaluating the actual min-width the component
// queries for — used to prove the five-column layout only turns on once
// there's genuinely enough room (see ConversationWorkspacePage.tsx's
// FIVE_COLUMN_MIN_WIDTH), not at MUI's stock `md` (900px), which used to
// leave the message thread only 40px wide.
function stubViewportWidth(width: number) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => {
    const match = /min-width:\s*([\d.]+)px/.exec(query)
    const minWidth = match ? Number(match[1]) : Infinity
    return {
      matches: width >= minWidth,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }
  }) as unknown as typeof window.matchMedia
}

describe('ConversationWorkspacePage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    // @ts-expect-error — restoring jsdom's real default (no matchMedia at
    // all), so this stub can't leak into any other test file.
    delete window.matchMedia
  })

  it('shows only the open conversation on mobile, without the filters or list columns', async () => {
    renderWorkspace()
    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: /filters and queues/i }),
    ).not.toBeInTheDocument()
  })

  it('shows all five columns on desktop: filters, list, conversation and details', async () => {
    stubDesktopViewport()
    renderWorkspace()

    // Filters & Queues is its own dedicated column, not tabs stacked
    // above the list.
    const filters = await screen.findByRole('navigation', { name: /filters and queues/i })
    expect(within(filters).getByText('Status')).toBeInTheDocument()
    expect(within(filters).getByText('Queues')).toBeInTheDocument()

    // The conversation column and the customer details column.
    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    // "Grace Blake" (the seeded conversation's customer) legitimately
    // renders more than once once every column is visible — once in the
    // list row, again in the conversation header/details panel.
    expect(await screen.findAllByText('Grace Blake')).not.toHaveLength(0)
  })

  it('the filters column filters the conversation list without touching the open conversation', async () => {
    const user = userEvent.setup()
    stubDesktopViewport()
    renderWorkspace()
    const filters = await screen.findByRole('navigation', { name: /filters and queues/i })
    await screen.findAllByText('Grace Blake')

    // The seeded conversation is "open" — selecting "Pending" in the
    // filters column empties the list, while the conversation column on
    // the right keeps showing the same open conversation.
    await user.click(within(filters).getByRole('button', { name: /^pending$/i }))

    expect(await screen.findByText(/nothing here/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^status/i)).toBeInTheDocument()
  })

  it('stays single-column at 1024px, too narrow for five columns', async () => {
    stubViewportWidth(1024)
    renderWorkspace()

    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: /filters and queues/i }),
    ).not.toBeInTheDocument()
  })

  it('shows every column once the viewport is wide enough for the message thread to stay usable', async () => {
    // FIVE_COLUMN_MIN_WIDTH is 1480 (260 nav + 220 filters + 320 list +
    // 280 details + 400 message minimum).
    stubViewportWidth(1500)
    renderWorkspace()

    expect(await screen.findByLabelText(/^status/i)).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /filters and queues/i })).toBeInTheDocument()
  })

  it('has no detectable accessibility violations on desktop', async () => {
    stubDesktopViewport()
    const { container } = renderWorkspace()
    await screen.findByLabelText(/^status/i)
    expect(await axe(container)).toHaveNoViolations()
  })
})
