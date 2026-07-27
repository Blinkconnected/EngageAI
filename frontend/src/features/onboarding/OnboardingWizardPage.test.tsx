import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { OnboardingWizardPage } from './OnboardingWizardPage'

function renderWizard() {
  return renderAuthenticated(
    <Routes>
      <Route path="/onboarding" element={<OnboardingWizardPage />} />
      <Route path="/" element={<div>Dashboard landing</div>} />
    </Routes>,
    ['/onboarding'],
  )
}

describe('OnboardingWizardPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    sessionStorage.clear()
  })

  it('shows the company information step first, pre-filled', async () => {
    renderWizard()
    expect(await screen.findByText('Set up Acme Corp')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Acme Corp')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations on the first step', async () => {
    const { container } = renderWizard()
    await screen.findByText('Set up Acme Corp')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('walks through Team Setup: shows the owner and invites an agent', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')

    await user.click(screen.getByRole('button', { name: /^next$/i }))

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Owner')).toBeInTheDocument()

    await user.type(screen.getByLabelText(/full name/i), 'New Agent')
    await user.type(screen.getByLabelText(/email/i), 'new-agent@acme.example')
    await user.click(screen.getByRole('button', { name: /invite agent/i }))

    expect(await screen.findByText('new-agent@acme.example')).toBeInTheDocument()
  })

  it('creates a department in Team Setup', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')
    await user.click(screen.getByRole('button', { name: /^next$/i }))
    await screen.findByText('Ada Lovelace')

    await user.type(screen.getByLabelText(/department name/i), 'Billing')
    await user.click(screen.getByRole('button', { name: /^create$/i }))

    expect(await screen.findByText('Billing')).toBeInTheDocument()
  })

  it('connects a channel in the Channels step', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')
    await user.click(screen.getByRole('button', { name: /^next$/i }))
    await screen.findByText('Ada Lovelace')
    await user.click(screen.getByRole('button', { name: /^next$/i }))

    await user.click(screen.getByRole('button', { name: /connect web chat/i }))
    const dialogTitle = await screen.findByText('Connect a channel')
    expect(dialogTitle).toBeInTheDocument()

    await user.type(screen.getByLabelText(/display name/i), 'Support Widget')
    await user.click(screen.getByRole('button', { name: /connect channel/i }))

    await waitFor(() => expect(screen.queryByText('Connect a channel')).not.toBeInTheDocument())
    expect(await screen.findByText('Support Widget')).toBeInTheDocument()
  })

  it('enables ERP and shows the connect form in the final step', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')
    await user.click(screen.getByRole('button', { name: /^next$/i }))
    await screen.findByText('Ada Lovelace')
    await user.click(screen.getByRole('button', { name: /^next$/i }))
    await screen.findByRole('button', { name: /connect whatsapp/i })
    await user.click(screen.getByRole('button', { name: /^next$/i }))

    expect(screen.queryByLabelText(/erpnext site url/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('switch', { name: /enable erp integration/i }))
    expect(await screen.findByLabelText(/erpnext site url/i)).toBeInTheDocument()
  })

  it('finishes onboarding and lands on the dashboard', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')

    for (let i = 0; i < 3; i += 1) {
      await user.click(screen.getByRole('button', { name: /^next$/i }))
    }

    await user.click(screen.getByRole('button', { name: /^finish$/i }))
    expect(await screen.findByText('Dashboard landing')).toBeInTheDocument()
  })

  it('skips setup from the first step and lands on the dashboard', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')

    await user.click(screen.getByRole('button', { name: /skip setup/i }))
    expect(await screen.findByText('Dashboard landing')).toBeInTheDocument()
  })

  it('supports going back a step', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByText('Set up Acme Corp')

    await user.click(screen.getByRole('button', { name: /^next$/i }))
    await screen.findByText('Ada Lovelace')
    await user.click(screen.getByRole('button', { name: /^back$/i }))

    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
  })
})
