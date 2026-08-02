import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Workload } from './inboxTypes'

async function fetchWorkload(): Promise<Workload> {
  const { data } = await apiClient.get<Workload>('/conversations/workload')
  return data
}

/** How many conversations are in each work queue.
 *
 * One request, every count, computed across the whole company — a count taken
 * from the loaded page would be wrong in exactly the situation it matters,
 * which is a busy queue.
 *
 * Refetched on an interval because this is the number an agent glances at to
 * know whether the shape of the day has changed. A stale "4 breached" is
 * worse than none: it is a fact they will act on.
 */
export function useWorkloadQuery() {
  return useQuery({
    queryKey: ['conversations', 'workload'],
    queryFn: fetchWorkload,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}
