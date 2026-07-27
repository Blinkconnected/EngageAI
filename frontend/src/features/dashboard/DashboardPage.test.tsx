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

  it('renders the enriched queue-depth table with department, waiting, wait-time and SLA-breach columns', async () => {
    renderAuthenticated(<DashboardPage />)

    // "General" (see mocks/handlers/dashboard.ts): department "Support",
    // 7 open, 3 waiting, avg wait 125s -> "2m 5s", longest wait 340s ->
    // "5m 40s", 2 SLA breaches. Cells are asserted by column position
    // (matching QueueDepthTable's own column order) rather than by text
    // alone, since several columns can legitimately share a value (e.g.
    // both waiting/SLA-breached are small integers).
    const generalRow = (await screen.findByText('General')).closest('tr') as HTMLElement
    const generalCells = within(generalRow).getAllByRole('cell')
    expect(generalCells[1]).toHaveTextContent('Support')
    expect(generalCells[2]).toHaveTextContent('7')
    expect(generalCells[3]).toHaveTextContent('3')
    expect(generalCells[4]).toHaveTextContent('2m 5s')
    expect(generalCells[5]).toHaveTextContent('5m 40s')
    expect(generalCells[6]).toHaveTextContent('2')

    // "VIP" has no department and null wait times (nothing has waited) —
    // proves the null -> "—" fallback, not just the happy path above.
    const vipRow = screen.getByText('VIP').closest('tr') as HTMLElement
    const vipCells = within(vipRow).getAllByRole('cell')
    expect(vipCells[1]).toHaveTextContent('—')
    expect(vipCells[2]).toHaveTextContent('5')
    expect(vipCells[3]).toHaveTextContent('0')
    expect(vipCells[4]).toHaveTextContent('—')
    expect(vipCells[5]).toHaveTextContent('—')
    expect(vipCells[6]).toHaveTextContent('0')
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
