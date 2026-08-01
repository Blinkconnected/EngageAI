import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PlatformPaymentProvidersPage } from './PlatformPaymentProvidersPage'
import { apiClient } from '../../shared/api/client'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const PROVIDERS = {
  providers: [
    {
      kind: 'efawateercom',
      label: 'eFAWATEERcom',
      description: 'Publish an invoice as a bill.',
      flow: 'bill_presentment',
      countries: ['JO'],
      fields: [
        {
          name: 'biller_code',
          label: 'Biller code',
          secret: false,
          required: true,
          help_text: null,
          choices: [],
        },
        {
          name: 'client_secret',
          label: 'Client secret',
          secret: true,
          required: true,
          help_text: null,
          choices: [],
        },
      ],
      enabled: true,
      readiness: 'awaiting_integration',
      missing: [],
      // A credential is stored — but its value is never sent to this screen.
      secret_set: { client_secret: true },
      values: { biller_code: '55' },
      pending_note: 'Integration specification not yet in this codebase.',
    },
  ],
  updated_by_email: 'ops@example.com',
  updated_at: '2026-08-01T00:00:00Z',
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PlatformPaymentProvidersPage />
    </QueryClientProvider>,
  )
}

describe('PlatformPaymentProvidersPage', () => {
  // Without this, `vi.spyOn` returns the *same* spy across tests and its
  // recorded calls accumulate — so `mock.calls[0]` in a later test is an
  // earlier test's request. That reads as a failure in the code rather than
  // in the test, which is the worst kind of red.
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a scheme that cannot be connected yet, and says why', async () => {
    // Storing credentials for a scheme with no adapter is legitimate; hiding
    // that it cannot yet take payments is not. An operator needs to know
    // before a customer discovers it.
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: PROVIDERS })

    renderPage()

    expect(await screen.findByText('eFAWATEERcom')).toBeInTheDocument()
    expect(
      screen.getByText('Integration specification not yet in this codebase.'),
    ).toBeInTheDocument()
    expect(screen.getByText('payments.readiness.awaiting_integration')).toBeInTheDocument()
  })

  it('never renders a stored secret into the form', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: PROVIDERS })

    renderPage()

    const secret = await screen.findByLabelText(/Client secret/)
    expect(secret).toHaveValue('')
  })

  it('does not resend a credential the operator did not retype', async () => {
    // The behaviour that protects every merchant account on the
    // installation. This screen is never given the stored secret, so if a
    // save sent the whole form back it would overwrite a working credential
    // with the blank it was shown — silently, with no error, and nothing
    // visibly wrong until a customer tried to pay.
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: PROVIDERS })
    const put = vi
      .spyOn(apiClient, 'put')
      .mockResolvedValue({ data: PROVIDERS.providers[0] })

    renderPage()

    const billerCode = await screen.findByLabelText(/Biller code/)
    await userEvent.clear(billerCode)
    await userEvent.type(billerCode, '77')
    await userEvent.click(screen.getByRole('button', { name: 'payments.save' }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    const [, body] = put.mock.calls[0] as [string, { values: Record<string, unknown> }]
    expect(body.values.biller_code).toBe('77')
    expect('client_secret' in body.values).toBe(false)
  })

  it('sends a secret the operator did retype', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: PROVIDERS })
    const put = vi
      .spyOn(apiClient, 'put')
      .mockResolvedValue({ data: PROVIDERS.providers[0] })

    renderPage()

    await userEvent.type(await screen.findByLabelText(/Client secret/), 'new-secret')
    await userEvent.click(screen.getByRole('button', { name: 'payments.save' }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    const [, body] = put.mock.calls[0] as [string, { values: Record<string, unknown> }]
    expect(body.values.client_secret).toBe('new-secret')
  })
})
