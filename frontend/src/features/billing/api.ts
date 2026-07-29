import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { SESSION_QUERY_KEY } from '../session/api'
import type { BillingOverview, Subscription } from './types'

const BILLING_KEY = ['billing', 'overview']

async function fetchOverview(): Promise<BillingOverview> {
  const { data } = await apiClient.get<BillingOverview>('/billing')
  return data
}

/** One request for the whole page: current subscription, the plans on
 * offer, and past payments. */
export function useBillingOverviewQuery() {
  return useQuery({ queryKey: BILLING_KEY, queryFn: fetchOverview })
}

async function subscribe(planId: string): Promise<Subscription> {
  const { data } = await apiClient.post<Subscription>('/billing/subscribe', { plan_id: planId })
  return data
}

export function useSubscribeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: subscribe,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: BILLING_KEY })
    },
  })
}

async function cancelSubscription(reason: string | null): Promise<Subscription> {
  const { data } = await apiClient.post<Subscription>('/billing/cancel', { reason })
  return data
}

export function useCancelSubscriptionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: cancelSubscription,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: BILLING_KEY })
      // The plan decides which features are on, so the profile that
      // drives the navigation is now stale.
      void queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY })
    },
  })
}
