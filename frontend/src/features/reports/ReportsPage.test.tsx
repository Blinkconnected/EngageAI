import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ReportsPage } from './ReportsPage'

function renderReports(initialPath = '/reports/executive') {
  return renderAuthenticated(
    <Routes>
      <Route path="/reports/:tab?" element={<ReportsPage />} />
    </Routes>,
    [initialPath],
  )
}

describe('ReportsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('redirects /reports to the executive tab and shows its KPIs', async () => {
    renderReports('/reports')
    expect(await screen.findByText('42')).toBeInTheDocument() // conversations_opened
    expect(screen.getByRole('tab', { name: 'Executive', selected: true })).toBeInTheDocument()
  })

  it('does not show the agent-only "My Performance" tab for an Owner', async () => {
    renderReports()
    await screen.findByText('42')
    expect(screen.queryByRole('tab', { name: 'My Performance' })).not.toBeInTheDocument()
  })

  it('switching to the Conversations tab loads that report', async () => {
    const user = userEvent.setup()
    renderReports()
    await screen.findByText('42')

    await user.click(screen.getByRole('tab', { name: 'Conversations' }))

    const table = await screen.findByRole('region', { name: 'Conversations report' })
    expect(within(table).getByText('whatsapp')).toBeInTheDocument()
    expect(within(table).getByText('web_chat')).toBeInTheDocument()
  })

  it('switching to the CSAT tab shows the average rating', async () => {
    const user = userEvent.setup()
    renderReports()
    await screen.findByText('42')

    await user.click(screen.getByRole('tab', { name: 'CSAT' }))

    expect(await screen.findByText('4.50')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderReports()
    await screen.findByText('42')
    expect(await axe(container)).toHaveNoViolations()
  })
})
