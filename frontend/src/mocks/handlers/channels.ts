import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  ChannelConfig,
  ChannelConfigCreateRequest,
  ChannelConfigUpdateRequest,
} from '../../features/channels/types'
import type { Page } from '../../shared/api/pagination'

const SEED_CHANNELS: ChannelConfig[] = [
  {
    id: 'c1',
    channel_type: 'telegram',
    display_name: 'Support Telegram',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

let channels: ChannelConfig[] = [...SEED_CHANNELS]
let nextId = 100

export function resetChannelsMock() {
  channels = [...SEED_CHANNELS]
  nextId = 100
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

  http.post(`${API_BASE_URL}/channel-configs`, async ({ request }) => {
    const payload = (await request.json()) as ChannelConfigCreateRequest
    const created: ChannelConfig = {
      id: `c${nextId}`,
      channel_type: payload.channel_type,
      display_name: payload.display_name,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextId += 1
    channels = [...channels, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch(`${API_BASE_URL}/channel-configs/:channelConfigId`, async ({ request, params }) => {
    const payload = (await request.json()) as ChannelConfigUpdateRequest
    const index = channels.findIndex((channel) => channel.id === params.channelConfigId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const { credentials: _credentials, webhook_secret: _webhookSecret, ...visible } = payload
    const updated = { ...channels[index], ...visible }
    channels = [...channels.slice(0, index), updated, ...channels.slice(index + 1)]
    return HttpResponse.json(updated)
  }),

  http.delete(`${API_BASE_URL}/channel-configs/:channelConfigId`, ({ params }) => {
    channels = channels.filter((channel) => channel.id !== params.channelConfigId)
    return new HttpResponse(null, { status: 204 })
  }),
]
