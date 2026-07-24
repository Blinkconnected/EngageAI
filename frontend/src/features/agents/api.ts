import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type { Agent, AgentCreateRequest, AgentUpdateRequest } from './types'

const AGENTS_LIST_KEY = ['agents', 'list']

async function fetchAgents(params: PageParams): Promise<Page<Agent>> {
  const { data } = await apiClient.get<Page<Agent>>('/agents', { params })
  return data
}

async function createAgent(payload: AgentCreateRequest): Promise<Agent> {
  const { data } = await apiClient.post<Agent>('/agents', payload)
  return data
}

async function updateAgent(agentId: string, payload: AgentUpdateRequest): Promise<Agent> {
  const { data } = await apiClient.patch<Agent>(`/agents/${agentId}`, payload)
  return data
}

async function deleteAgent(agentId: string): Promise<void> {
  await apiClient.delete(`/agents/${agentId}`)
}

export function useAgentsQuery(params: PageParams) {
  return useQuery({
    queryKey: [...AGENTS_LIST_KEY, params],
    queryFn: () => fetchAgents(params),
    placeholderData: (previousData) => previousData,
  })
}

export function useCreateAgentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createAgent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENTS_LIST_KEY }),
  })
}

export function useUpdateAgentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: AgentUpdateRequest }) =>
      updateAgent(agentId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENTS_LIST_KEY }),
  })
}

export function useDeleteAgentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteAgent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENTS_LIST_KEY }),
  })
}
