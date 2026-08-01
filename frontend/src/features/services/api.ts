import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  Service,
  ServiceCreateRequest,
  ServiceDetail,
  ServiceSaved,
  ServiceUpdateRequest,
  ServiceVersion,
} from './types'

const SERVICES_KEY = ['services', 'list']

export function useServicesQuery() {
  return useQuery({
    queryKey: SERVICES_KEY,
    queryFn: async (): Promise<Service[]> => {
      const { data } = await apiClient.get<Service[]>('/services')
      return data
    },
  })
}

export function useServiceQuery(serviceId: string | null) {
  return useQuery({
    queryKey: ['services', 'detail', serviceId],
    enabled: serviceId !== null,
    queryFn: async (): Promise<ServiceDetail> => {
      const { data } = await apiClient.get<ServiceDetail>(`/services/${serviceId}`)
      return data
    },
  })
}

/** Every configuration this service has ever had, newest first. Conversations
 * are still running on some of them, which is why none can be deleted. */
export function useServiceVersionsQuery(serviceId: string | null) {
  return useQuery({
    queryKey: ['services', 'versions', serviceId],
    enabled: serviceId !== null,
    queryFn: async (): Promise<ServiceVersion[]> => {
      const { data } = await apiClient.get<ServiceVersion[]>(`/services/${serviceId}/versions`)
      return data
    },
  })
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ['services'] })
}

export function useCreateServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ServiceCreateRequest): Promise<ServiceSaved> => {
      const { data } = await apiClient.post<ServiceSaved>('/services', payload)
      return data
    },
    onSuccess: () => invalidate(queryClient),
  })
}

export function useUpdateServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      serviceId,
      changes,
    }: {
      serviceId: string
      changes: ServiceUpdateRequest
    }): Promise<ServiceSaved> => {
      const { data } = await apiClient.patch<ServiceSaved>(`/services/${serviceId}`, changes)
      return data
    },
    onSuccess: () => invalidate(queryClient),
  })
}

export function useArchiveServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (serviceId: string): Promise<void> => {
      await apiClient.delete(`/services/${serviceId}`)
    },
    onSuccess: () => invalidate(queryClient),
  })
}
