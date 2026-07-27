import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  Queue,
  QueueCreateRequest,
  QueueUpdateRequest,
  RoutingRule,
  RoutingRuleCreateRequest,
  RoutingRuleUpdateRequest,
} from './types'

const QUEUES_LIST_KEY = ['queues', 'list']
const ROUTING_RULES_KEY = ['routing-rules', 'list']

async function fetchQueues(params: PageParams): Promise<Page<Queue>> {
  const { data } = await apiClient.get<Page<Queue>>('/queues', { params })
  return data
}

async function fetchAllQueues(): Promise<Queue[]> {
  const { data } = await apiClient.get<Page<Queue>>('/queues', {
    params: { page: 1, page_size: 100 },
  })
  return data.items
}

async function createQueue(payload: QueueCreateRequest): Promise<Queue> {
  const { data } = await apiClient.post<Queue>('/queues', payload)
  return data
}

async function updateQueue(queueId: string, payload: QueueUpdateRequest): Promise<Queue> {
  const { data } = await apiClient.patch<Queue>(`/queues/${queueId}`, payload)
  return data
}

async function deleteQueue(queueId: string): Promise<void> {
  await apiClient.delete(`/queues/${queueId}`)
}

async function fetchRoutingRules(): Promise<RoutingRule[]> {
  const { data } = await apiClient.get<RoutingRule[]>('/routing-rules')
  return data
}

async function createRoutingRule(payload: RoutingRuleCreateRequest): Promise<RoutingRule> {
  const { data } = await apiClient.post<RoutingRule>('/routing-rules', payload)
  return data
}

async function updateRoutingRule(
  ruleId: string,
  payload: RoutingRuleUpdateRequest,
): Promise<RoutingRule> {
  const { data } = await apiClient.patch<RoutingRule>(`/routing-rules/${ruleId}`, payload)
  return data
}

async function deleteRoutingRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/routing-rules/${ruleId}`)
}

/** A paginated view for the Queues management page's data table — distinct
 * from `useAllQueuesQuery` below, which every picker/dropdown elsewhere in
 * the app uses instead. */
export function useQueuesQuery(params: PageParams) {
  return useQuery({
    queryKey: [...QUEUES_LIST_KEY, params],
    queryFn: () => fetchQueues(params),
    placeholderData: (previousData) => previousData,
  })
}

/** Full-list fetch for lookups/pickers (Inbox's queue filter, a
 * conversation's queue reassignment dropdown, the routing-rule target
 * picker) — organizations rarely have more than a handful of queues, so
 * this is proportionate rather than premature. */
export function useAllQueuesQuery() {
  return useQuery({
    queryKey: ['queues', 'all'],
    queryFn: fetchAllQueues,
    staleTime: 60_000,
  })
}

function invalidateQueues(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: QUEUES_LIST_KEY })
  queryClient.invalidateQueries({ queryKey: ['queues', 'all'] })
}

export function useCreateQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createQueue,
    onSuccess: () => invalidateQueues(queryClient),
  })
}

export function useUpdateQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ queueId, payload }: { queueId: string; payload: QueueUpdateRequest }) =>
      updateQueue(queueId, payload),
    onSuccess: () => invalidateQueues(queryClient),
  })
}

export function useDeleteQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteQueue,
    onSuccess: () => invalidateQueues(queryClient),
  })
}

/** Not paginated — this app's routing rules are a short, priority-ordered
 * list meant to be seen and reordered as a whole, not browsed a page at a
 * time (matching the backend's own unpaginated `GET /routing-rules`). */
export function useRoutingRulesQuery() {
  return useQuery({
    queryKey: ROUTING_RULES_KEY,
    queryFn: fetchRoutingRules,
  })
}

function invalidateRoutingRules(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ROUTING_RULES_KEY })
}

export function useCreateRoutingRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createRoutingRule,
    onSuccess: () => invalidateRoutingRules(queryClient),
  })
}

export function useUpdateRoutingRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, payload }: { ruleId: string; payload: RoutingRuleUpdateRequest }) =>
      updateRoutingRule(ruleId, payload),
    onSuccess: () => invalidateRoutingRules(queryClient),
  })
}

export function useDeleteRoutingRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteRoutingRule,
    onSuccess: () => invalidateRoutingRules(queryClient),
  })
}
