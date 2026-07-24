import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type { ChannelConfig, ChannelConfigCreateRequest, ChannelConfigUpdateRequest } from './types'

const CHANNELS_LIST_KEY = ['channels', 'list']

async function fetchChannels(params: PageParams): Promise<Page<ChannelConfig>> {
  const { data } = await apiClient.get<Page<ChannelConfig>>('/channel-configs', { params })
  return data
}

async function createChannel(payload: ChannelConfigCreateRequest): Promise<ChannelConfig> {
  const { data } = await apiClient.post<ChannelConfig>('/channel-configs', payload)
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHANNELS_LIST_KEY }),
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
