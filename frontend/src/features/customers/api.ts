import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  Customer,
  CustomerCreateRequest,
  CustomerInternalRating,
  CustomerInternalRatingRequest,
  CustomerUpdateRequest,
} from './types'

const CUSTOMERS_LIST_KEY = ['customers', 'list']
const CUSTOMER_KEY = (customerId: string) => ['customers', 'detail', customerId]
const CUSTOMER_RATINGS_KEY = (customerId: string) => ['customers', customerId, 'ratings']

async function fetchCustomers(params: PageParams & { search?: string }): Promise<Page<Customer>> {
  const { data } = await apiClient.get<Page<Customer>>('/customers', { params })
  return data
}

async function fetchCustomer(customerId: string): Promise<Customer> {
  const { data } = await apiClient.get<Customer>(`/customers/${customerId}`)
  return data
}

async function createCustomer(payload: CustomerCreateRequest): Promise<Customer> {
  const { data } = await apiClient.post<Customer>('/customers', payload)
  return data
}

async function updateCustomer(
  customerId: string,
  payload: CustomerUpdateRequest,
): Promise<Customer> {
  const { data } = await apiClient.patch<Customer>(`/customers/${customerId}`, payload)
  return data
}

async function fetchCustomerRatings(
  customerId: string,
  params: PageParams,
): Promise<Page<CustomerInternalRating>> {
  const { data } = await apiClient.get<Page<CustomerInternalRating>>(
    `/customers/${customerId}/ratings`,
    { params },
  )
  return data
}

async function createCustomerRating(
  customerId: string,
  payload: CustomerInternalRatingRequest,
): Promise<CustomerInternalRating> {
  const { data } = await apiClient.post<CustomerInternalRating>(
    `/customers/${customerId}/ratings`,
    payload,
  )
  return data
}

async function updateCustomerRating(
  customerId: string,
  ratingId: string,
  payload: CustomerInternalRatingRequest,
): Promise<CustomerInternalRating> {
  const { data } = await apiClient.patch<CustomerInternalRating>(
    `/customers/${customerId}/ratings/${ratingId}`,
    payload,
  )
  return data
}

async function deleteCustomerRating(customerId: string, ratingId: string): Promise<void> {
  await apiClient.delete(`/customers/${customerId}/ratings/${ratingId}`)
}

export function useCustomersQuery(params: PageParams & { search?: string }) {
  return useQuery({
    queryKey: [...CUSTOMERS_LIST_KEY, params],
    queryFn: () => fetchCustomers(params),
    placeholderData: (previousData) => previousData,
  })
}

/** Cached per-id — safe to call once per Inbox row without re-fetching on
 * every render, and shared with the Customer profile page. */
export function useCustomerQuery(customerId: string | undefined) {
  return useQuery({
    queryKey: CUSTOMER_KEY(customerId ?? ''),
    queryFn: () => fetchCustomer(customerId as string),
    enabled: Boolean(customerId),
    staleTime: 60_000,
  })
}

export function useCreateCustomerMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createCustomer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CUSTOMERS_LIST_KEY }),
  })
}

export function useUpdateCustomerMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CustomerUpdateRequest) => updateCustomer(customerId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(CUSTOMER_KEY(customerId), data)
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_LIST_KEY })
    },
  })
}

export function useCustomerRatingsQuery(customerId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...CUSTOMER_RATINGS_KEY(customerId ?? ''), params],
    queryFn: () => fetchCustomerRatings(customerId as string, params),
    enabled: Boolean(customerId),
  })
}

/** All three rating mutations invalidate the customer's own detail cache
 * (and the customers list) alongside the ratings list — `rating_average`/
 * `rating_count` are embedded fields on `Customer`, computed server-side
 * from this same table, so both caches go stale together. */
function invalidateAfterRatingChange(
  queryClient: ReturnType<typeof useQueryClient>,
  customerId: string,
) {
  void queryClient.invalidateQueries({ queryKey: CUSTOMER_RATINGS_KEY(customerId) })
  void queryClient.invalidateQueries({ queryKey: CUSTOMER_KEY(customerId) })
  void queryClient.invalidateQueries({ queryKey: CUSTOMERS_LIST_KEY })
}

export function useCreateCustomerRatingMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CustomerInternalRatingRequest) =>
      createCustomerRating(customerId, payload),
    onSuccess: () => invalidateAfterRatingChange(queryClient, customerId),
  })
}

export function useUpdateCustomerRatingMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      ratingId,
      payload,
    }: {
      ratingId: string
      payload: CustomerInternalRatingRequest
    }) => updateCustomerRating(customerId, ratingId, payload),
    onSuccess: () => invalidateAfterRatingChange(queryClient, customerId),
  })
}

export function useDeleteCustomerRatingMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ratingId: string) => deleteCustomerRating(customerId, ratingId),
    onSuccess: () => invalidateAfterRatingChange(queryClient, customerId),
  })
}
