import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  ChannelConfig,
  ChannelConfigCreateRequest,
  ChannelConfigCreateResult,
  ChannelConfigUpdateRequest,
  ChannelConnectionLog,
  TestConnectionRequest,
  TestConnectionResult,
} from '../../features/channels/types'
import type { Page } from '../../shared/api/pagination'

const SEED_CHANNELS: ChannelConfig[] = [
  {
    id: 'c1',
    channel_type: 'telegram',
    display_name: 'Support Telegram',
    is_active: true,
    last_health_status: 'healthy',
    last_health_checked_at: '2026-01-02T00:00:00Z',
    last_health_detail: null,
    last_health_origin: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

let channels: ChannelConfig[] = [...SEED_CHANNELS]
let logs: Record<string, ChannelConnectionLog[]> = {
  c1: [
    {
      id: 'log-1',
      event_type: 'created',
      level: 'info',
      message: "Channel 'Support Telegram' (telegram) connected.",
      log_metadata: {},
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
}
let nextId = 100
let nextLogId = 100

export function resetChannelsMock() {
  channels = [...SEED_CHANNELS]
  logs = {
    c1: [
      {
        id: 'log-1',
        event_type: 'created',
        level: 'info',
        message: "Channel 'Support Telegram' (telegram) connected.",
        log_metadata: {},
        created_at: '2026-01-01T00:00:00Z',
      },
    ],
  }
  nextId = 100
  nextLogId = 100
}

function addLog(channelConfigId: string, entry: Omit<ChannelConnectionLog, 'id' | 'created_at'>) {
  const log: ChannelConnectionLog = {
    ...entry,
    id: `log-${nextLogId}`,
    created_at: '2026-01-02T00:00:00Z',
  }
  nextLogId += 1
  logs[channelConfigId] = [log, ...(logs[channelConfigId] ?? [])]
}

function testConnectionResult(credentials: Record<string, unknown>): TestConnectionResult {
  if (credentials.fail_health_check) {
    // Tests can pass a specific origin via fail_health_check (e.g.
    // 'provider'/'configuration'/'network'/'internal'); a bare truthy
    // value (e.g. `true`) falls back to 'provider', matching "the
    // provider's servers rejected this," the most common simulated case.
    const origin =
      typeof credentials.fail_health_check === 'string'
        ? (credentials.fail_health_check as TestConnectionResult['origin'])
        : 'provider'
    return { healthy: false, detail: 'simulated failure', origin }
  }
  return { healthy: true, detail: null, origin: null }
}

export const channelsHandlers = [
  http.get(`${API_BASE_URL}/channel-configs`, ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '20')
    const start = (page - 1) * pageSize
    const body: Page<ChannelConfig> = {
      items: channels.slice(start, start + pageSize),
      total: channels.length,
      page,
      page_size: pageSize,
    }
    return HttpResponse.json(body)
  }),

  http.post(`${API_BASE_URL}/channel-configs/test-connection`, async ({ request }) => {
    const payload = (await request.json()) as TestConnectionRequest
    return HttpResponse.json(testConnectionResult(payload.credentials))
  }),

  http.post(`${API_BASE_URL}/channel-configs`, async ({ request }) => {
    const payload = (await request.json()) as ChannelConfigCreateRequest
    const created: ChannelConfigCreateResult = {
      id: `c${nextId}`,
      channel_type: payload.channel_type,
      display_name: payload.display_name,
      is_active: true,
      last_health_status: null,
      last_health_checked_at: null,
      last_health_detail: null,
      last_health_origin: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      webhook_secret: payload.webhook_secret || 'mock-generated-webhook-secret',
      verify_token:
        payload.channel_type === 'whatsapp'
          ? ((payload.credentials.verify_token as string | undefined) ??
            'mock-generated-verify-token')
          : null,
    }
    nextId += 1
    channels = [...channels, created]
    addLog(created.id, {
      event_type: 'created',
      level: 'info',
      message: `Channel '${created.display_name}' (${created.channel_type}) connected.`,
      log_metadata: {},
    })
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/channel-configs/:channelConfigId`, async ({ request, params }) => {
    const payload = (await request.json()) as ChannelConfigUpdateRequest
    const index = channels.findIndex((channel) => channel.id === params.channelConfigId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const { credentials, webhook_secret: _webhookSecret, ...visible } = payload
    const updated = { ...channels[index], ...visible }
    channels = [...channels.slice(0, index), updated, ...channels.slice(index + 1)]
    if (credentials) {
      addLog(updated.id, {
        event_type: 'credentials_updated',
        level: 'info',
        message: 'Credentials were updated (reconnect flow).',
        log_metadata: {},
      })
    }
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/channel-configs/:channelConfigId`, ({ params }) => {
    channels = channels.filter((channel) => channel.id !== params.channelConfigId)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE_URL}/channel-configs/:channelConfigId/test-connection`, ({ params }) => {
    const index = channels.findIndex((channel) => channel.id === params.channelConfigId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const result: TestConnectionResult = { healthy: true, detail: null, origin: null }
    channels[index] = {
      ...channels[index],
      last_health_status: result.healthy ? 'healthy' : 'unhealthy',
      last_health_checked_at: '2026-01-02T00:00:00Z',
      last_health_detail: result.detail,
      last_health_origin: result.origin,
    }
    addLog(channels[index].id, {
      event_type: 'test_connection_succeeded',
      level: 'info',
      message: 'Connection OK.',
      log_metadata: {},
    })
    return HttpResponse.json(result)
  }),

  http.get(
    `${API_BASE_URL}/channel-configs/:channelConfigId/connection-logs`,
    ({ params, request }) => {
      const channelConfigId = String(params.channelConfigId)
      const url = new URL(request.url)
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '20')
      const items = logs[channelConfigId] ?? []
      const start = (page - 1) * pageSize
      const body: Page<ChannelConnectionLog> = {
        items: items.slice(start, start + pageSize),
        total: items.length,
        page,
        page_size: pageSize,
      }
      return HttpResponse.json(body)
    },
  ),
]
