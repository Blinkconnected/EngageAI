import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { LiveDashboard } from './types'

async function fetchLiveDashboard(): Promise<LiveDashboard> {
  const { data } = await apiClient.get<LiveDashboard>('/reports/live-dashboard')
  return data
}

export function useLiveDashboardQuery() {
  return useQuery({
    queryKey: ['reports', 'live-dashboard'],
    queryFn: fetchLiveDashboard,
    // A live operational snapshot, not a historical report — refetch often
    // enough that agents/supervisors watching this page see current state.
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}
