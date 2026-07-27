import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { MOCK_USER } from '../../mocks/handlers/auth'
import type { ChannelConfig } from '../channels/types'
import { StatusPage } from './StatusPage'

function channelsPage(items: ChannelConfig[]) {
  return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100 })
}

function channel(
  overrides: Partial<ChannelConfig> & Pick<ChannelConfig, 'id' | 'channel_type'>,
): ChannelConfig {
  return {
    display_name: overrides.channel_type,
    is_active: true,
    last_health_status: null,
    last_health_checked_at: null,
    last_health_detail: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function cardFor(label: string): HTMLElement {
  return screen.getByText(label).closest('.MuiCard-root') as HTMLElement
}

describe('StatusPage', () => {
  afterEach(() => {
    cleanup()
    server.resetHandlers()
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows an aggregate status per channel type, including types with nothing connected', async () => {
    server.use(
      http.get(`${API_BASE_URL}/channel-configs`, () =>
        channelsPage([
          channel({
            id: 'wa1',
            channel_type: 'whatsapp',
            display_name: 'Main WhatsApp',
            last_health_status: 'unhealthy',
            last_health_detail: 'Token expired',
            last_health_checked_at: '2026-01-02T00:00:00Z',
          }),
          channel({
            id: 'em1',
            channel_type: 'email',
            display_name: 'Support Inbox',
          }),
          channel({
            id: 'sms1',
            channel_type: 'sms',
            display_name: 'Old SMS line',
            is_active: false,
          }),
          channel({
            id: 'tg1',
            channel_type: 'telegram',
            display_name: 'Support Telegram',
            last_health_status: 'healthy',
            last_health_checked_at: '2026-01-02T00:00:00Z',
          }),
        ]),
      ),
    )
    renderAuthenticated(<StatusPage />)
    await screen.findByText('WhatsApp Business')

    // Each card's aggregate status is asserted via its own testid rather
    // than a bare `getByText`, since an aggregate label can legitimately
    // repeat text also shown by an individual ChannelHealthBadge within
    // the same card (e.g. "Not tested yet" appears both as the Email
    // card's aggregate status and its one config's own health badge).
    const whatsappCard = cardFor('WhatsApp Business')
    expect(within(whatsappCard).getByTestId('channel-type-status')).toHaveTextContent('Degraded')

    const emailCard = cardFor('Email')
    expect(within(emailCard).getByTestId('channel-type-status')).toHaveTextContent('Not tested yet')

    const smsCard = cardFor('SMS')
    expect(within(smsCard).getByTestId('channel-type-status')).toHaveTextContent('Inactive')

    const telegramCard = cardFor('Telegram')
    expect(within(telegramCard).getByTestId('channel-type-status')).toHaveTextContent('Operational')

    // Instagram and Facebook Messenger have no connected channel at all.
    const instagramCard = cardFor('Instagram')
    expect(within(instagramCard).getByTestId('channel-type-status')).toHaveTextContent(
      'Not configured',
    )
    expect(
      within(instagramCard).getByText('No Instagram channel connected yet.'),
    ).toBeInTheDocument()
  })

  it('lets a channels.manage holder test an individual channel and check all at once', async () => {
    const user = userEvent.setup()
    let testCallCount = 0
    server.use(
      http.get(`${API_BASE_URL}/channel-configs`, () =>
        channelsPage([
          channel({ id: 'tg1', channel_type: 'telegram', display_name: 'Support Telegram' }),
        ]),
      ),
      http.post(`${API_BASE_URL}/channel-configs/:id/test-connection`, () => {
        testCallCount += 1
        return HttpResponse.json({ healthy: true, detail: null })
      }),
    )
    renderAuthenticated(<StatusPage />)

    await screen.findByText('Support Telegram')
    await user.click(screen.getByRole('button', { name: 'Test Connection' }))
    await waitFor(() => expect(testCallCount).toBe(1))

    await user.click(screen.getByRole('button', { name: 'Check all now' }))
    await waitFor(() => expect(testCallCount).toBe(2))
  })

  it('hides test-connection actions for a user without channels.manage', async () => {
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'channels.manage'),
        }),
      ),
      http.get(`${API_BASE_URL}/channel-configs`, () =>
        channelsPage([
          channel({ id: 'tg1', channel_type: 'telegram', display_name: 'Support Telegram' }),
        ]),
      ),
    )
    renderAuthenticated(<StatusPage />)

    await screen.findByText('Support Telegram')
    expect(screen.queryByRole('button', { name: 'Test Connection' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check all now' })).not.toBeInTheDocument()
  })

  it('shows every channel type as not configured when nothing is connected', async () => {
    server.use(http.get(`${API_BASE_URL}/channel-configs`, () => channelsPage([])))
    renderAuthenticated(<StatusPage />)

    await screen.findByText('WhatsApp Business')
    const whatsappCard = cardFor('WhatsApp Business')
    expect(within(whatsappCard).getByTestId('channel-type-status')).toHaveTextContent(
      'Not configured',
    )
    expect(screen.getByRole('button', { name: 'Check all now' })).toBeDisabled()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<StatusPage />)
    await screen.findByText('Support Telegram')
    expect(await axe(container)).toHaveNoViolations()
  })
})
