import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  BillingDashboard,
  BillingEstimate,
  ChartWindow,
  DailySeries,
  InvoiceDetail,
  ProjectionStrategy,
} from './types'

/**
 * How often the estimate re-polls, in milliseconds.
 *
 * The requirement is 30–60 seconds; 45 sits in the middle. React Query does
 * not poll a background tab (`refetchIntervalInBackground` defaults to
 * false), so a page left open on another monitor costs nothing until it is
 * looked at again — and `refetchOnWindowFocus` means coming back to the tab
 * updates immediately rather than after up to 45 seconds of a stale number.
 */
export const ESTIMATE_REFRESH_MS = 45_000

async function fetchDashboard(): Promise<BillingDashboard> {
  const { data } = await apiClient.get<BillingDashboard>('/billing/dashboard')
  return data
}

/**
 * Everything the page needs, in one request. See the endpoint's docstring for
 * why this is one call rather than eight.
 *
 * Deliberately keyed on **nothing**. The projection strategy and the chart
 * window each change one section, and re-keying the whole page on either would
 * empty `data` for the new key and re-read invoices, rates and payment
 * configuration — none of which the change affects — while that one section
 * reloads. The strategy belongs to the estimate query and the window to the
 * daily query; the dashboard's own copies are the first paint.
 */
export function useBillingDashboardQuery() {
  return useQuery({
    queryKey: ['billing', 'dashboard'],
    queryFn: fetchDashboard,
  })
}

async function fetchEstimate(strategy: ProjectionStrategy | null): Promise<BillingEstimate> {
  const { data } = await apiClient.get<BillingEstimate>('/billing/estimate', {
    params: strategy ? { strategy } : undefined,
  })
  return data
}

/**
 * The live figures: today, month-to-date and the projection.
 *
 * Seeded from the dashboard response for the **default** strategy, so opening
 * the page makes one request rather than two — `initialData` plus
 * `initialDataUpdatedAt` tells React Query the data is as fresh as the
 * dashboard call that produced it, so the first poll happens 45 seconds later
 * instead of immediately. Choosing another strategy has no seed, so that one
 * is fetched: the server owns every projection, and the page never recomputes
 * one from a different method's numbers.
 */
export function useBillingEstimateQuery(
  strategy: ProjectionStrategy | null,
  { enabled, seed }: { enabled: boolean; seed?: { data: BillingEstimate; at: number } | undefined },
) {
  return useQuery({
    queryKey: ['billing', 'estimate', strategy],
    queryFn: () => fetchEstimate(strategy),
    refetchInterval: ESTIMATE_REFRESH_MS,
    refetchOnWindowFocus: true,
    enabled,
    initialData: seed?.data,
    initialDataUpdatedAt: seed?.at,
  })
}

async function fetchDaily(window: ChartWindow): Promise<DailySeries> {
  const { data } = await apiClient.get<DailySeries>('/billing/daily', { params: { window } })
  return data
}

/** The cost chart on its own, for switching windows without refetching the
 * whole page. */
export function useDailyCostQuery(window: ChartWindow, enabled = true) {
  return useQuery({
    queryKey: ['billing', 'daily', window],
    queryFn: () => fetchDaily(window),
    enabled,
  })
}

async function fetchInvoice(invoiceId: string): Promise<InvoiceDetail> {
  const { data } = await apiClient.get<InvoiceDetail>(`/billing/invoices/${invoiceId}`)
  return data
}

export function useInvoiceDetailQuery(invoiceId: string | null) {
  return useQuery({
    queryKey: ['billing', 'invoice', invoiceId],
    queryFn: () => fetchInvoice(invoiceId as string),
    enabled: invoiceId !== null,
  })
}
