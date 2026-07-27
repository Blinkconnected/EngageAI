import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { QueuesPage } from './QueuesPage'

describe('QueuesPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists existing queues', async () => {
    renderAuthenticated(<QueuesPage />)
    expect(await screen.findByText('General')).toBeInTheDocument()
    expect(screen.getByText('VIP')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<QueuesPage />)
    await screen.findByText('General')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('creates a new queue through the dialog', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<QueuesPage />)
    await screen.findByText('General')

    await user.click(screen.getByRole('button', { name: /new queue/i }))
    await user.type(await screen.findByLabelText(/^name/i), 'Billing')
    await user.click(screen.getByRole('button', { name: /create queue/i }))

    expect(await screen.findByText('Billing')).toBeInTheDocument()
  })

  it('assigns an SLA policy to a queue through the edit dialog', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<QueuesPage />)
    const row = (await screen.findByText('VIP')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    const policyField = await screen.findByLabelText(/^sla policy/i)
    await user.click(policyField)
    await user.click(await screen.findByRole('option', { name: 'Standard' }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.queryByText(/edit vip/i)).not.toBeInTheDocument())
  })

  it('edits a queue name and active status', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<QueuesPage />)
    const row = (await screen.findByText('VIP')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Edit'))
    const nameField = await screen.findByLabelText(/^name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Priority Support')
    await user.click(screen.getByRole('switch', { name: /active/i }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText('Priority Support')).toBeInTheDocument())
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('deletes a queue after confirming', async () => {
    // "General" (unlike "VIP") has no routing rule targeting it — see
    // the next test for that guarded case.
    const user = userEvent.setup()
    renderAuthenticated(<QueuesPage />)
    const row = (await screen.findByText('General')).closest('[role="row"]')
    expect(row).not.toBeNull()

    await user.click(within(row as HTMLElement).getByLabelText('Delete'))
    await user.click(await screen.findByRole('button', { name: /^remove$/i }))

    await waitFor(() => expect(screen.queryByText('General')).not.toBeInTheDocument())
  })

  it('blocks deleting a queue a routing rule still targets', async () => {
    renderAuthenticated(<QueuesPage />)
    const row = (await screen.findByText('VIP')).closest('[role="row"]')
    expect(row).not.toBeNull()

    expect(
      within(row as HTMLElement).getByLabelText(/routing rule\(s\) still target this queue/),
    ).toBeDisabled()
  })

  it('does not offer create/edit/delete without queues.manage', async () => {
    const { server } = await import('../../mocks/server')
    const { http, HttpResponse } = await import('msw')
    const { API_BASE_URL } = await import('../../mocks/apiBaseUrl')
    const { MOCK_USER } = await import('../../mocks/handlers/auth')
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'queues.manage'),
        }),
      ),
    )
    renderAuthenticated(<QueuesPage />)
    await screen.findByText('General')

    expect(screen.queryByRole('button', { name: /new queue/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Edit')).not.toBeInTheDocument()
  })

  describe('Routing Rules tab', () => {
    async function openRoutingRulesTab(user: ReturnType<typeof userEvent.setup>) {
      renderAuthenticated(<QueuesPage />)
      await screen.findByText('General')
      await user.click(screen.getByRole('tab', { name: /routing rules/i }))
    }

    it('lists existing routing rules with their condition and target queue', async () => {
      const user = userEvent.setup()
      await openRoutingRulesTab(user)

      expect(await screen.findByText('Channel is Web Chat')).toBeInTheDocument()
      expect(screen.getByText('VIP')).toBeInTheDocument()
    })

    it('has no detectable accessibility violations', async () => {
      const user = userEvent.setup()
      const { container } = renderAuthenticated(<QueuesPage />)
      await screen.findByText('General')
      await user.click(screen.getByRole('tab', { name: /routing rules/i }))
      await screen.findByText('Channel is Web Chat')

      expect(await axe(container)).toHaveNoViolations()
    })

    it('creates a new routing rule through the dialog', async () => {
      const user = userEvent.setup()
      await openRoutingRulesTab(user)
      await screen.findByText('Channel is Web Chat')

      await user.click(screen.getByRole('button', { name: /new routing rule/i }))
      await user.click(await screen.findByLabelText(/route to queue/i))
      await user.click(await screen.findByRole('option', { name: 'General' }))
      await user.type(screen.getByLabelText(/message contains/i), 'refund')
      await user.click(screen.getByRole('button', { name: /create rule/i }))

      expect(await screen.findByText(/message contains "refund"/i)).toBeInTheDocument()
    })

    it('edits a routing rule', async () => {
      const user = userEvent.setup()
      await openRoutingRulesTab(user)
      const row = (await screen.findByText('Channel is Web Chat')).closest('tr')
      expect(row).not.toBeNull()

      await user.click(within(row as HTMLElement).getByLabelText('Edit routing rule'))
      const priorityField = await screen.findByLabelText(/^priority/i)
      await user.clear(priorityField)
      await user.type(priorityField, '5')
      await user.click(screen.getByRole('button', { name: /save changes/i }))

      await waitFor(() => expect(screen.getByText('5')).toBeInTheDocument())
    })

    it('deletes a routing rule after confirming', async () => {
      const user = userEvent.setup()
      await openRoutingRulesTab(user)
      const row = (await screen.findByText('Channel is Web Chat')).closest('tr')
      expect(row).not.toBeNull()

      await user.click(within(row as HTMLElement).getByLabelText('Delete routing rule'))
      await user.click(await screen.findByRole('button', { name: /^remove$/i }))

      await waitFor(() => expect(screen.queryByText('Channel is Web Chat')).not.toBeInTheDocument())
      expect(await screen.findByText('No routing rules yet')).toBeInTheDocument()
    })
  })
})
