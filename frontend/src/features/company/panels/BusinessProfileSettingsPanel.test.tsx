import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../../../mocks/server'
import { API_BASE_URL } from '../../../mocks/apiBaseUrl'
import { store } from '../../../app/store'
import { queryClient } from '../../../app/queryClient'
import { loggedOut } from '../../auth/authSlice'
import { renderAuthenticated } from '../../../test/renderAuthenticated'
import { resetCompanyMock } from '../../../mocks/handlers/company'
import type { BusinessProfileSettings, Company } from '../types'
import { BusinessProfileSettingsPanel } from './BusinessProfileSettingsPanel'

const COMPANY: Company = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Acme Corp',
  slug: 'acme-corp',
  status: 'active',
  settings: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function withProfile(profile: BusinessProfileSettings): Company {
  return { ...COMPANY, settings: { business_profile: profile } }
}

interface PatchBody {
  settings?: { business_profile?: BusinessProfileSettings }
}

/** Asserting on the request body rather than re-rendered UI: this panel
 * takes `company` as a prop, so in isolation it never sees the saved
 * value come back — and the payload is what decides what the AI is told. */
function capturePatchedSettings() {
  const captured: { body: PatchBody | null } = { body: null }
  server.use(
    http.patch(`${API_BASE_URL}/company`, async ({ request }) => {
      captured.body = (await request.json()) as PatchBody
      return HttpResponse.json({ ...COMPANY, settings: captured.body?.settings ?? {} })
    }),
  )
  return captured
}

describe('BusinessProfileSettingsPanel', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetCompanyMock()
  })

  it('sends a filled-in fact so AI can state it', async () => {
    const user = userEvent.setup()
    const captured = capturePatchedSettings()
    renderAuthenticated(<BusinessProfileSettingsPanel company={COMPANY} />)

    await user.type(await screen.findByLabelText(/company name/i), 'Blink Connected')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body?.settings?.business_profile?.legal_name).toBe('Blink Connected')
  })

  it('sends a cleared field as an explicit null rather than omitting it', async () => {
    /** The regression this guards. `CompanyService._merge_settings`
     * merges a section one level deep, so an omitted field keeps its
     * stored value. Omitting blanks would make *clearing* impossible: an
     * administrator deletes the address, is told it saved, and AI keeps
     * quoting the old one. */
    const user = userEvent.setup()
    const captured = capturePatchedSettings()
    renderAuthenticated(
      <BusinessProfileSettingsPanel
        company={withProfile({ legal_name: 'Blink Connected', location: 'Old Address' })}
      />,
    )

    await user.clear(await screen.findByLabelText(/^location/i))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    const sent = captured.body?.settings?.business_profile
    expect(sent).toHaveProperty('location')
    expect(sent?.location).toBeNull()
    // The field that was not touched still goes out intact.
    expect(sent?.legal_name).toBe('Blink Connected')
  })

  it('trims surrounding whitespace so a space-only entry counts as blank', async () => {
    const user = userEvent.setup()
    const captured = capturePatchedSettings()
    renderAuthenticated(<BusinessProfileSettingsPanel company={COMPANY} />)

    await user.type(await screen.findByLabelText(/company name/i), '  Blink Connected  ')
    await user.type(screen.getByLabelText(/^location/i), '   ')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body?.settings?.business_profile?.legal_name).toBe('Blink Connected')
    expect(captured.body?.settings?.business_profile?.location).toBeNull()
  })

  it('keeps Save disabled until something actually changes', async () => {
    renderAuthenticated(
      <BusinessProfileSettingsPanel company={withProfile({ legal_name: 'Blink Connected' })} />,
    )

    expect(await screen.findByRole('button', { name: /save changes/i })).toBeDisabled()
  })

  it('points at the Business Hours tab rather than offering a second hours field', async () => {
    /** One source of truth: hours live in the structured schedule, so
     * the hours AI quotes and the hours the SLA engine honours cannot
     * drift apart. */
    renderAuthenticated(<BusinessProfileSettingsPanel company={COMPANY} />)

    expect(await screen.findByText(/opening hours come from the business hours tab/i)).toBeVisible()
    expect(screen.queryByLabelText(/business hours/i)).not.toBeInTheDocument()
  })
})
