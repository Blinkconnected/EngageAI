import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { DashboardPage } from './DashboardPage'

describe('DashboardPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows a working landing page instead of a broken error state for a role without reports.read', async () => {
    // Dashboard is the one nav item shown to every authenticated user
    // (the post-login destination), unlike every other item, which is
    // hidden for a role lacking its permission — a custom role built in
    // Roles & Permissions (chat-only, knowledge-only) can omit
    // reports.read, and this page has to still work for them.
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    const { MOCK_USER } = await import('../../mocks/handlers/auth')
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'reports.read'),
        }),
      ),
    )

    renderAuthenticated(<DashboardPage />)

    expect(await screen.findByText(/no reports access/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /go to inbox/i })).toHaveAttribute(
      'href',
      '/conversations',
    )
    expect(screen.queryByText(/total conversations/i)).not.toBeInTheDocument()
  })

  it('renders the enriched queue-depth table with department, stage, wait-time and SLA-breach columns', async () => {
    renderAuthenticated(<DashboardPage />)

    // "General" (see mocks/handlers/dashboard.ts): department "Support", 7
    // open, 3 waiting, 1 picked, 3 active, 10 resolved/8 closed in the last
    // 24h, avg wait 125s -> "2m 5s", longest wait 340s -> "5m 40s", 2 SLA
    // breaches. Cells are asserted by column position (matching
    // QueueDepthTable's own column order: queue, department, flow,
    // waiting, picked, active, resolved-24h, closed-24h, avg wait, longest
    // wait, SLA breached) rather than by text alone, since several columns
    // can legitimately share a value (e.g. waiting/SLA-breached).
    const generalRow = (await screen.findByText('General')).closest('tr') as HTMLElement
    const generalCells = within(generalRow).getAllByRole('cell')
    expect(generalCells[1]).toHaveTextContent('Support')
    expect(generalCells[2]).toHaveTextContent('7')
    expect(generalCells[3]).toHaveTextContent('3')
    expect(generalCells[4]).toHaveTextContent('1')
    expect(generalCells[5]).toHaveTextContent('3')
    expect(generalCells[6]).toHaveTextContent('10')
    expect(generalCells[7]).toHaveTextContent('8')
    expect(generalCells[8]).toHaveTextContent('2m 5s')
    expect(generalCells[9]).toHaveTextContent('5m 40s')
    expect(generalCells[10]).toHaveTextContent('2')

    // "VIP" has no department and null wait times (nothing has waited) —
    // proves the null -> "—" fallback, not just the happy path above.
    const vipRow = screen.getByText('VIP').closest('tr') as HTMLElement
    const vipCells = within(vipRow).getAllByRole('cell')
    expect(vipCells[1]).toHaveTextContent('—')
    expect(vipCells[2]).toHaveTextContent('5')
    expect(vipCells[3]).toHaveTextContent('0')
    expect(vipCells[4]).toHaveTextContent('2')
    expect(vipCells[5]).toHaveTextContent('3')
    expect(vipCells[6]).toHaveTextContent('6')
    expect(vipCells[7]).toHaveTextContent('3')
    expect(vipCells[8]).toHaveTextContent('—')
    expect(vipCells[9]).toHaveTextContent('—')
    expect(vipCells[10]).toHaveTextContent('0')
  })

  it('shows a company-wide queue flow chart above the per-queue table', async () => {
    renderAuthenticated(<DashboardPage />)

    expect(await screen.findByText('Queue flow (all queues)')).toBeInTheDocument()
  })

  it('shows a 4th "busy" chip alongside online/away/offline', async () => {
    renderAuthenticated(<DashboardPage />)

    expect(await screen.findByText('3 online')).toBeInTheDocument()
    expect(screen.getByText('1 away')).toBeInTheDocument()
    expect(screen.getByText('2 busy')).toBeInTheDocument()
    expect(screen.getByText('2 offline')).toBeInTheDocument()
  })

  it('shows total/active/unassigned conversation summary cards', async () => {
    renderAuthenticated(<DashboardPage />)

    // See mocks/handlers/dashboard.ts: open 12 + pending 4 + resolved 30 +
    // closed 55 = total 101; active = open + pending = 16; unassigned = 3.
    // Each card's value is asserted within its own card (rather than a
    // bare `getByText`) since a small integer like "3" also legitimately
    // appears elsewhere on the page (e.g. the queue depth table).
    const totalCard = (await screen.findByText('Total conversations')).closest(
      '.MuiCard-root',
    ) as HTMLElement
    expect(within(totalCard).getByText('101')).toBeInTheDocument()

    const activeCard = screen
      .getByText('Active (open + pending)')
      .closest('.MuiCard-root') as HTMLElement
    expect(within(activeCard).getByText('16')).toBeInTheDocument()

    const unassignedCard = screen.getByText('Unassigned').closest('.MuiCard-root') as HTMLElement
    expect(within(unassignedCard).getByText('3')).toBeInTheDocument()
  })

  it('shows the live SLA-breached count, and only emphasizes it when non-zero', async () => {
    // The fixture seeds sla_breached: 2 — a live "still open/pending and
    // already past an SLA target" figure, distinct from the SLA report's
    // retrospective date-ranged breach counts.
    renderAuthenticated(<DashboardPage />)

    // Selected by the stat's own aria-label, not its visible text — the
    // queue depth table further down has an "SLA breached" column header
    // with the same wording.
    const breachedCard = (await screen.findByLabelText('SLA breached: 2')).closest(
      '.MuiCard-root',
    ) as HTMLElement
    expect(breachedCard).toBeInTheDocument()

    // Non-zero reads as an alert, unlike the neutral counts beside it.
    const totalCard = screen.getByText('Total conversations').closest('.MuiCard-root') as HTMLElement
    expect(breachedCard.className).not.toEqual(totalCard.className)
  })

  it('does not emphasize the SLA-breached card when nothing is breaching', async () => {
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    const { MOCK_LIVE_DASHBOARD } = await import('../../mocks/handlers/dashboard')

    server.use(
      http.get(`${API_BASE_URL}/reports/live-dashboard`, () =>
        HttpResponse.json({
          ...MOCK_LIVE_DASHBOARD,
          conversations: { ...MOCK_LIVE_DASHBOARD.conversations, sla_breached: 0 },
        }),
      ),
    )
    queryClient.clear()
    renderAuthenticated(<DashboardPage />)

    const breachedCard = (await screen.findByLabelText('SLA breached: 0')).closest(
      '.MuiCard-root',
    ) as HTMLElement
    expect(breachedCard).toBeInTheDocument()

    const totalCard = screen.getByText('Total conversations').closest('.MuiCard-root') as HTMLElement
    expect(breachedCard.className).toEqual(totalCard.className)
  })

  it("renders the team workload table with each agent's open/pending/total counts", async () => {
    renderAuthenticated(<DashboardPage />)

    // See mocks/handlers/dashboard.ts: Grace Blake has 5 open, 1 pending,
    // total 6; Priya Nair is idle (0/0/0) and still appears, not omitted.
    const graceRow = (await screen.findByText('Grace Blake')).closest('tr') as HTMLElement
    const graceCells = within(graceRow).getAllByRole('cell')
    expect(graceCells[1]).toHaveTextContent('5')
    expect(graceCells[2]).toHaveTextContent('1')
    expect(graceCells[3]).toHaveTextContent('6')

    const priyaRow = screen.getByText('Priya Nair').closest('tr') as HTMLElement
    const priyaCells = within(priyaRow).getAllByRole('cell')
    expect(priyaCells[1]).toHaveTextContent('0')
    expect(priyaCells[2]).toHaveTextContent('0')
    expect(priyaCells[3]).toHaveTextContent('0')
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<DashboardPage />)
    await screen.findByText('General')
    expect(await axe(container)).toHaveNoViolations()
  })
})
