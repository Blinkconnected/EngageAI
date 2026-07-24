import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type { Customer, CustomerCreateRequest, CustomerUpdateRequest } from './types'

const CUSTOMERS_LIST_KEY = ['customers', 'list']
const CUSTOMER_KEY = (customerId: string) => ['customers', 'detail', customerId]

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
