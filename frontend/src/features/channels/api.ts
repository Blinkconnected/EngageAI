import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  ChannelConfig,
  ChannelConfigCreateRequest,
  ChannelConfigCreateResult,
  ChannelConfigUpdateRequest,
  ChannelConnectionLog,
  TestConnectionRequest,
  TestConnectionResult,
} from './types'

const CHANNELS_LIST_KEY = ['channels', 'list']
const CONNECTION_LOGS_KEY = (channelConfigId: string) => ['channels', channelConfigId, 'logs']

async function fetchChannels(params: PageParams): Promise<Page<ChannelConfig>> {
  const { data } = await apiClient.get<Page<ChannelConfig>>('/channel-configs', { params })
  return data
}

async function createChannel(
  payload: ChannelConfigCreateRequest,
): Promise<ChannelConfigCreateResult> {
  const { data } = await apiClient.post<ChannelConfigCreateResult>('/channel-configs', payload)
  return data
}

async function updateChannel(
  channelConfigId: string,
  payload: ChannelConfigUpdateRequest,
): Promise<ChannelConfig> {
  const { data } = await apiClient.patch<ChannelConfig>(
    `/channel-configs/${channelConfigId}`,
    payload,
  )
  return data
}

async function deleteChannel(channelConfigId: string): Promise<void> {
  await apiClient.delete(`/channel-configs/${channelConfigId}`)
}

async function testConnectionEphemeral(
  payload: TestConnectionRequest,
): Promise<TestConnectionResult> {
  const { data } = await apiClient.post<TestConnectionResult>(
    '/channel-configs/test-connection',
    payload,
  )
  return data
}

async function testConnection(channelConfigId: string): Promise<TestConnectionResult> {
  const { data } = await apiClient.post<TestConnectionResult>(
    `/channel-configs/${channelConfigId}/test-connection`,
  )
  return data
}

async function fetchConnectionLogs(
  channelConfigId: string,
  params: PageParams,
): Promise<Page<ChannelConnectionLog>> {
  const { data } = await apiClient.get<Page<ChannelConnectionLog>>(
    `/channel-configs/${channelConfigId}/connection-logs`,
    { params },
  )
  return data
}

export function useChannelsQuery(params: PageParams) {
  return useQuery({
    queryKey: [...CHANNELS_LIST_KEY, params],
    queryFn: () => fetchChannels(params),
    placeholderData: (previousData) => previousData,
  })
}

/** Full-list fetch for lookups (e.g. resolving a conversation's
 * channel_config_id to a display name/type in the Inbox) — companies
 * rarely run more than a handful of channels. */
export function useAllChannelsQuery() {
  return useQuery({
    queryKey: ['channels', 'all'],
    queryFn: () => fetchChannels({ page: 1, page_size: 100 }),
    staleTime: 60_000,
    select: (data) => data.items,
  })
}

export function useCreateChannelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CHANNELS_LIST_KEY })
      // Also invalidate the unpaginated lookup list (e.g. the Company
      // Onboarding Wizard's Channels step) — a distinct query key from
      // CHANNELS_LIST_KEY above, so it wouldn't otherwise refresh until
      // its own 60s staleTime lapsed.
      queryClient.invalidateQueries({ queryKey: ['channels', 'all'] })
    },
  })
}

export function useUpdateChannelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      channelConfigId,
      payload,
    }: {
      channelConfigId: string
      payload: ChannelConfigUpdateRequest
    }) => updateChannel(channelConfigId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_LIST_KEY }),
  })
}

export function useDeleteChannelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteChannel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_LIST_KEY }),
  })
}

/** Guided setup wizard's "Test Connection" step, before anything is saved. */
export function useTestConnectionEphemeralMutation() {
  return useMutation({ mutationFn: testConnectionEphemeral })
}

/** Re-check an already-saved channel — reconnect flow / health monitoring
 * detail view. Also invalidates the list so a just-updated health badge
 * shows up without a manual refresh. */
export function useTestConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: testConnection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_LIST_KEY }),
  })
}

export function useConnectionLogsQuery(channelConfigId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...CONNECTION_LOGS_KEY(channelConfigId ?? ''), params],
    queryFn: () => fetchConnectionLogs(channelConfigId as string, params),
    enabled: Boolean(channelConfigId),
    placeholderData: (previousData) => previousData,
  })
}
