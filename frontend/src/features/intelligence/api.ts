import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { LearningThresholds, ShadowMetrics, ThresholdUpdateResult, UnclusteredObservation } from './types'

/** The pilot dashboard, in one request.
 *
 * One call rather than twelve, matching the endpoint. An operator
 * deciding whether the pilot is healthy should not watch twelve spinners
 * resolve in an order that tells them nothing about the answer.
 *
 * Polled at a minute, not a second. Every number here moves on a sweep
 * cadence measured in hours, so a faster poll would only cost queries and
 * make the page flicker under somebody reading it.
 */
export function useShadowMetrics(days = 30) {
  return useQuery({
    queryKey: ['learning-shadow', days],
    queryFn: async (): Promise<ShadowMetrics> => {
      const { data } = await apiClient.get<ShadowMetrics>('/intelligence/shadow', {
        params: { days },
      })
      return data
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

/** What the platform could not group, and why.
 *
 * Loaded separately from the metrics because it is a *list*, and one an
 * operator opens deliberately when a number above it looks wrong — not
 * something to fetch on every dashboard poll.
 */
export function useUnclustered(limit = 50, enabled = true) {
  return useQuery({
    queryKey: ['learning-unclustered', limit],
    queryFn: async (): Promise<UnclusteredObservation[]> => {
      const { data } = await apiClient.get<UnclusteredObservation[]>('/intelligence/unclustered', {
        params: { limit },
      })
      return data
    },
    enabled,
    staleTime: 60_000,
  })
}

export function useLearningThresholds() {
  return useQuery({
    queryKey: ['learning-thresholds'],
    queryFn: async (): Promise<LearningThresholds> => {
      const { data } = await apiClient.get<LearningThresholds>('/intelligence/thresholds')
      return data
    },
    staleTime: 60_000,
  })
}

/** Change a threshold.
 *
 * Invalidates the dashboard as well as the thresholds, because a change
 * reshapes every cluster the next sweep produces — leaving the old
 * numbers on screen beside the new threshold would be actively
 * misleading.
 */
export function useUpdateThresholds() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: {
      cluster_join_threshold?: number
      cluster_merge_threshold?: number
      reason?: string
    }): Promise<ThresholdUpdateResult> => {
      const { data } = await apiClient.patch<ThresholdUpdateResult>('/intelligence/thresholds', payload)
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['learning-thresholds'] })
      void queryClient.invalidateQueries({ queryKey: ['learning-shadow'] })
    },
  })
}
