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

/** Full-list fetch for lookups (e.g. resolving a conversation's
 * assigned_agent_id to a name in the Inbox, or populating an "assign to"
 * picker) — a company's agent roster is rarely large enough to need
 * paginated lookup UI. */
export function useAllAgentsQuery() {
  return useQuery({
    queryKey: ['agents', 'all'],
    queryFn: () => fetchAgents({ page: 1, page_size: 100 }),
    staleTime: 30_000,
    select: (data) => data.items,
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
