import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { CompanySettingsPage } from './CompanySettingsPage'

// `useCompanyLogoUrl` is stubbed (real exports kept via importOriginal) —
// jsdom's Blob doesn't implement `.stream()`, which MSW's Response
// construction needs for any blob-typed response, so the real fetch path
// can't run here. Same documented tooling gap as AttachmentList.test.tsx/
// AppLayout.test.tsx.
vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    useCompanyLogoUrl: (logoKey: string | null | undefined) => ({
      data: logoKey ? 'blob:mock-logo-url' : undefined,
    }),
  }
})

function renderWithRoutes(initialEntry = '/settings/company/general') {
  return renderAuthenticated(
    <Routes>
      <Route path="/settings/company/:tab?" element={<CompanySettingsPage />} />
    </Routes>,
    [initialEntry],
  )
}

describe('CompanySettingsPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('redirects to the general tab when no tab is given', async () => {
    renderWithRoutes('/settings/company/')
    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
  })

  it('shows the current company name and slug on the general tab', async () => {
    renderWithRoutes()
    expect(await screen.findByDisplayValue('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('acme-corp')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('saves a new company name', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    const nameField = await screen.findByDisplayValue('Acme Corp')

    await user.clear(nameField)
    await user.type(nameField, 'New Name Inc')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('does not show the ERP tab by default', async () => {
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')
    expect(screen.queryByRole('tab', { name: 'ERP' })).not.toBeInTheDocument()
  })

  it('enabling ERP on the general tab reveals the ERP tab', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')

    await user.click(screen.getByRole('switch', { name: /enable erp integration/i }))

    const erpTab = await screen.findByRole('tab', { name: 'ERP' })
    await user.click(erpTab)
    expect(await screen.findByLabelText(/erpnext site url/i)).toBeInTheDocument()
  })

  it('navigates between tabs and shows each panel', async () => {
    const user = userEvent.setup()
    renderWithRoutes()
    await screen.findByDisplayValue('Acme Corp')

    await user.click(screen.getByRole('tab', { name: 'Language' }))
    expect(await screen.findByLabelText(/default language/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Timezone' }))
    expect(await screen.findByRole('combobox', { name: /^timezone$/i })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Business Hours' }))
    expect(await screen.findByLabelText(/enable business hours/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Notifications' }))
    expect(await screen.findByText(/company-wide/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Messaging' }))
    expect(await screen.findByLabelText(/typing indicator/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Security' }))
    expect(await screen.findByLabelText(/minimum password length/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'AI' }))
    expect(await screen.findByLabelText(/enable ai engine features/i)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Branding' }))
    expect(await screen.findByRole('button', { name: /upload logo/i })).toBeInTheDocument()
  })

  it('uploads a branding logo', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/branding')

    await screen.findByRole('button', { name: /upload logo/i })
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['fake-png-bytes'], 'logo.png', { type: 'image/png' })

    await user.upload(fileInput, file)

    await waitFor(() => expect(screen.getByText('Logo updated.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /change logo/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove logo/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^upload logo$/i })).not.toBeInTheDocument()
  })

  it('removes a branding logo', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/branding')

    await screen.findByRole('button', { name: /upload logo/i })
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(fileInput, new File(['fake-png-bytes'], 'logo.png', { type: 'image/png' }))
    await screen.findByRole('button', { name: /remove logo/i })

    await user.click(screen.getByRole('button', { name: /remove logo/i }))

    await waitFor(() => expect(screen.getByText('Logo removed.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /upload logo/i })).toBeInTheDocument()
  })

  it('saves the default language', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/language')

    await user.click(await screen.findByLabelText(/default language/i))
    await user.click(await screen.findByRole('option', { name: 'Arabic' }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('saves business hours', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/business-hours')

    await user.click(await screen.findByLabelText(/enable business hours/i))
    expect(await screen.findByLabelText(/monday opens at/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('toggles a company-wide notification policy', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/notifications')

    const toggle = await screen.findByRole('switch', { name: /enable new conversation assigned/i })
    expect(toggle).toBeChecked()
    await user.click(toggle)

    await waitFor(() => expect(toggle).not.toBeChecked())
  })

  it('toggles the typing indicator', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/messaging')

    const toggle = await screen.findByLabelText(/typing indicator/i)
    expect(toggle).toBeChecked()
    await user.click(toggle)
    expect(toggle).not.toBeChecked()
  })

  it('rejects an out-of-range minimum password length', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/security')

    const field = await screen.findByLabelText(/minimum password length/i)
    await user.clear(field)
    await user.type(field, '5')

    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })

  it('saves a raised minimum password length', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/security')

    const field = await screen.findByLabelText(/minimum password length/i)
    await user.clear(field)
    await user.type(field, '16')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
  })

  it('toggles AI features off', async () => {
    const user = userEvent.setup()
    renderWithRoutes('/settings/company/ai')

    const toggle = await screen.findByLabelText(/enable ai engine features/i)
    expect(toggle).toBeChecked()
    await user.click(toggle)
    expect(toggle).not.toBeChecked()
  })

  describe('AI provider configuration', () => {
    it('defaults to Platform default with no key field shown', async () => {
      renderWithRoutes('/settings/company/ai')

      await screen.findByLabelText(/^provider/i)
      expect(screen.getByText('Platform default')).toBeInTheDocument()
      expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument()
    })

    it('requires an API key before saving OpenAI/Claude, and saves once one is entered', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      await user.click(await screen.findByRole('option', { name: 'OpenAI' }))

      const saveButton = screen.getByRole('button', { name: /save provider settings/i })
      expect(saveButton).toBeDisabled()

      await user.type(screen.getByLabelText(/api key/i), 'sk-test-key-value')
      expect(saveButton).toBeEnabled()

      await user.click(saveButton)
      expect(await screen.findByText('Saved.')).toBeInTheDocument()
      // The key itself is never echoed back into the DOM anywhere.
      expect(screen.queryByDisplayValue('sk-test-key-value')).not.toBeInTheDocument()
    })

    it('does not require re-entering the key when only changing the model', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      await user.click(await screen.findByRole('option', { name: 'OpenAI' }))
      await user.type(screen.getByLabelText(/api key/i), 'sk-test-key-value')
      await user.click(screen.getByRole('button', { name: /save provider settings/i }))
      await screen.findByText('Saved.')

      await user.type(screen.getByLabelText(/^model/i), 'gpt-4o')
      const saveButton = screen.getByRole('button', { name: /save provider settings/i })
      expect(saveButton).toBeEnabled()
      await user.click(saveButton)

      expect(await screen.findByText('Saved.')).toBeInTheDocument()
      expect(screen.getByLabelText(/api key/i)).toHaveAccessibleDescription(/already saved/i)
    })

    it('ollama does not require an API key', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      await user.click(await screen.findByRole('option', { name: /ollama/i }))

      expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument()
      await user.type(screen.getByLabelText(/base url/i), 'http://localhost:11434')
      expect(screen.getByRole('button', { name: /save provider settings/i })).toBeEnabled()
    })

    it('has no detectable accessibility violations with the provider section expanded', async () => {
      const user = userEvent.setup()
      const { container } = renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      await user.click(await screen.findByRole('option', { name: 'OpenAI' }))
      await screen.findByLabelText(/api key/i)

      expect(await axe(container)).toHaveNoViolations()
    })

    it('offers every newly supported provider', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      for (const label of ['Gemini (Google)', 'Azure OpenAI', 'Mistral', 'Groq', 'DeepSeek']) {
        expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
      }
    })

    it('azure openai requires a resource endpoint and a deployment name, not just a key', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')

      await user.click(await screen.findByLabelText(/^provider/i))
      await user.click(await screen.findByRole('option', { name: 'Azure OpenAI' }))

      const saveButton = screen.getByRole('button', { name: /save provider settings/i })
      await user.type(screen.getByLabelText(/api key/i), 'az-test-key')
      expect(saveButton).toBeDisabled()

      await user.type(screen.getByLabelText(/resource endpoint/i), 'https://acme.openai.azure.com')
      expect(saveButton).toBeDisabled()

      await user.type(screen.getByLabelText(/deployment name/i), 'acme-gpt4')
      expect(saveButton).toBeEnabled()

      await user.click(saveButton)
      expect(await screen.findByText('Saved.')).toBeInTheDocument()
    })
  })

  describe('AI Autopilot configuration', () => {
    it('is off with the default confidence threshold until enabled', async () => {
      renderWithRoutes('/settings/company/ai')

      await screen.findByLabelText(/^provider/i)
      expect(screen.getByRole('switch', { name: /enable ai autopilot/i })).not.toBeChecked()
      expect(screen.queryByLabelText(/confidence threshold/i)).not.toBeInTheDocument()
    })

    it('enables autopilot and saves a confidence threshold', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')
      await screen.findByLabelText(/^provider/i)

      await user.click(screen.getByRole('switch', { name: /enable ai autopilot/i }))
      const thresholdField = screen.getByLabelText(/confidence threshold/i)
      await user.clear(thresholdField)
      await user.type(thresholdField, '85')

      const saveButton = screen.getByRole('button', { name: /save autopilot settings/i })
      expect(saveButton).toBeEnabled()
      await user.click(saveButton)

      expect(await screen.findByText('Saved.')).toBeInTheDocument()
    })

    it('rejects an out-of-range confidence threshold', async () => {
      const user = userEvent.setup()
      renderWithRoutes('/settings/company/ai')
      await screen.findByLabelText(/^provider/i)

      await user.click(screen.getByRole('switch', { name: /enable ai autopilot/i }))
      const thresholdField = screen.getByLabelText(/confidence threshold/i)
      await user.clear(thresholdField)
      await user.type(thresholdField, '150')

      expect(screen.getByRole('button', { name: /save autopilot settings/i })).toBeDisabled()
    })
  })
})
