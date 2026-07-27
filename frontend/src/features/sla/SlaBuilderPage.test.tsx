import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { SlaBuilderPage } from './SlaBuilderPage'

describe('SlaBuilderPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists existing SLA policies', async () => {
    renderAuthenticated(<SlaBuilderPage />)
    expect(await screen.findByText('Standard')).toBeInTheDocument()
    expect(screen.getByText('30 min')).toBeInTheDocument()
    expect(screen.getByText('240 min')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<SlaBuilderPage />)
    await screen.findByText('Standard')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('creates a new SLA policy with an escalation rule', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<SlaBuilderPage />)
    await screen.findByText('Standard')

    await user.click(screen.getByRole('button', { name: /new policy/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Priority')
    await user.click(screen.getByRole('button', { name: /add escalation rule/i }))
    await user.click(screen.getByRole('button', { name: /create policy/i }))

    expect(await screen.findByText('Priority')).toBeInTheDocument()
  })

  it('edits a policy warning threshold', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<SlaBuilderPage />)
    const row = (await screen.findByText('Standard')).closest('tr') as HTMLElement

    await user.click(within(row).getByLabelText(/^edit standard$/i))
    const warningField = await screen.findByLabelText(/warning threshold/i)
    await user.clear(warningField)
    await user.type(warningField, '90')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('90%')).toBeInTheDocument())
  })

  it('deletes an unassigned policy after confirming', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<SlaBuilderPage />)
    const row = (await screen.findByText('Standard')).closest('tr') as HTMLElement

    await user.click(within(row).getByLabelText(/^delete standard$/i))
    await user.click(await screen.findByRole('button', { name: /^remove$/i }))

    await waitFor(() => expect(screen.queryByText('Standard')).not.toBeInTheDocument())
  })

  it('creates and deletes a holiday', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<SlaBuilderPage />)
    await screen.findByText('Standard')
    await user.click(screen.getByRole('tab', { name: /holidays/i }))
    await screen.findByText("New Year's Day")

    await user.click(screen.getByRole('button', { name: /new holiday/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Company Retreat')
    await user.type(screen.getByLabelText(/^date/i), '2027-06-15')
    await user.click(screen.getByRole('button', { name: /add holiday/i }))
    expect(await screen.findByText('Company Retreat')).toBeInTheDocument()

    const row = screen.getByText('Company Retreat').closest('tr') as HTMLElement
    await user.click(within(row).getByLabelText(/^delete company retreat$/i))
    await waitFor(() => expect(screen.queryByText('Company Retreat')).not.toBeInTheDocument())
  })

  it('previews computed SLA deadlines for a policy', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<SlaBuilderPage />)
    await screen.findByText('Standard')
    await user.click(screen.getByRole('tab', { name: /preview/i }))

    await user.click(await screen.findByLabelText(/^policy/i))
    await user.click(await screen.findByRole('option', { name: 'Standard' }))
    fireEvent.change(screen.getByLabelText(/conversation created at/i), {
      target: { value: '2027-01-15T09:00' },
    })
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByText('First response deadline')).toBeInTheDocument()
    expect(screen.getByText('Resolution deadline')).toBeInTheDocument()
  })

  it('does not offer create/edit/delete without sla_policies.manage', async () => {
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    const { MOCK_USER } = await import('../../mocks/handlers/auth')
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'sla_policies.manage'),
        }),
      ),
    )
    renderAuthenticated(<SlaBuilderPage />)
    await screen.findByText('Standard')

    expect(screen.queryByRole('button', { name: /new policy/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^edit standard$/i)).not.toBeInTheDocument()
  })
})
