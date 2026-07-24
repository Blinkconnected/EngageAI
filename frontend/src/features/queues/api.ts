import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type { Queue } from './types'

async function fetchAllQueues(): Promise<Queue[]> {
  const { data } = await apiClient.get<Page<Queue>>('/queues', {
    params: { page: 1, page_size: 100 },
  })
  return data.items
}

/** Full-list fetch for lookups/pickers — a dedicated Queues management
 * page (create/edit/delete, routing rules) is deferred to the secondary-
 * pages polish milestone, same precedent as Departments. */
export function useAllQueuesQuery() {
  return useQuery({
    queryKey: ['queues', 'all'],
    queryFn: fetchAllQueues,
    staleTime: 60_000,
  })
}
