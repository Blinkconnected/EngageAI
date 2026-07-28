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
import type { Company } from '../types'
import { AiSettingsPanel } from './AiSettingsPanel'

const COMPANY: Company = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Acme Corp',
  slug: 'acme-corp',
  status: 'active',
  settings: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

interface PatchBody {
  settings?: {
    ai?: {
      autopilot?: {
        enabled?: boolean
        confidence_threshold?: number
        activate_on_new_conversation?: boolean
        activate_on_sla?: boolean
        activate_on_agent_request?: boolean
      }
    }
  }
}

/** Captures the body of the next `PATCH /company`. Asserting on the
 * request rather than on re-rendered UI is deliberate here: this panel
 * receives `company` as a prop, so in isolation it never sees the saved
 * value come back, and the payload is the thing that actually matters
 * (see the one-level-deep merge note on the last test). */
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

/** AI Autopilot's three activation modes (see
 * `docs/architecture/ai-engine.md`). The modes only appear once the
 * master switch is on — with Autopilot disabled there is nothing for
 * them to govern. */
async function enableAutopilot(user: ReturnType<typeof userEvent.setup>) {
  const master = await screen.findByRole('switch', { name: /enable ai autopilot/i })
  await user.click(master)
  return master
}

describe('AiSettingsPanel — AI Autopilot activation modes', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    resetCompanyMock()
  })

  it('hides the activation modes until Autopilot itself is enabled', async () => {
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await screen.findByRole('switch', { name: /enable ai autopilot/i })

    expect(screen.queryByText(/when should autopilot step in/i)).not.toBeInTheDocument()
  })

  it('offers all three activation modes, with only the new-conversation mode on by default', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await enableAutopilot(user)

    expect(await screen.findByText(/when should autopilot step in/i)).toBeInTheDocument()
    // Defaults mirror the backend's readers exactly: the mode that
    // predates modes is on, the two new ones are opt-in.
    expect(screen.getByRole('switch', { name: /on a new conversation/i })).toBeChecked()
    expect(
      screen.getByRole('switch', { name: /close to missing .* response target/i }),
    ).not.toBeChecked()
    expect(screen.getByRole('switch', { name: /only when an agent asks/i })).not.toBeChecked()
  })

  it('saves the SLA trigger mode', async () => {
    const user = userEvent.setup()
    const patched = capturePatchedSettings()
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await enableAutopilot(user)

    await user.click(
      await screen.findByRole('switch', { name: /close to missing .* response target/i }),
    )
    await user.click(screen.getByRole('button', { name: /^save autopilot settings$/i }))

    await waitFor(() => expect(patched.body?.settings?.ai?.autopilot).toBeDefined())
    expect(patched.body?.settings?.ai?.autopilot?.activate_on_sla).toBe(true)
  })

  it('saves the agent-request mode independently of the others', async () => {
    const user = userEvent.setup()
    const patched = capturePatchedSettings()
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await enableAutopilot(user)

    // Turning the default mode off and the agent-request mode on proves
    // the three are genuinely independent, not one radio choice.
    await user.click(await screen.findByRole('switch', { name: /on a new conversation/i }))
    await user.click(screen.getByRole('switch', { name: /only when an agent asks/i }))
    await user.click(screen.getByRole('button', { name: /^save autopilot settings$/i }))

    await waitFor(() => expect(patched.body?.settings?.ai?.autopilot).toBeDefined())
    const autopilot = patched.body?.settings?.ai?.autopilot
    expect(autopilot?.activate_on_agent_request).toBe(true)
    expect(autopilot?.activate_on_new_conversation).toBe(false)
    expect(autopilot?.activate_on_sla).toBe(false)
  })

  it('warns when Autopilot is enabled but no activation mode can start it', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await enableAutopilot(user)

    await user.click(await screen.findByRole('switch', { name: /on a new conversation/i }))

    expect(await screen.findByText(/has no way to start/i)).toBeInTheDocument()
  })

  it('sends the complete autopilot object, so the backend one-level-deep merge cannot drop a mode', async () => {
    const user = userEvent.setup()
    const patched = capturePatchedSettings()
    renderAuthenticated(<AiSettingsPanel company={COMPANY} />)
    await enableAutopilot(user)
    await user.click(await screen.findByRole('switch', { name: /only when an agent asks/i }))
    await user.click(screen.getByRole('button', { name: /^save autopilot settings$/i }))

    // CompanyService merges settings exactly one level deep, so a PATCH
    // carrying a partial `ai.autopilot` replaces the whole sub-object.
    // Every key must therefore be present on every save.
    await waitFor(() => expect(patched.body?.settings?.ai?.autopilot).toBeDefined())
    expect(Object.keys(patched.body!.settings!.ai!.autopilot!).sort()).toEqual([
      'activate_on_agent_request',
      'activate_on_new_conversation',
      'activate_on_sla',
      'confidence_threshold',
      'enabled',
    ])
  })
})
