import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  Holiday,
  HolidayCreateRequest,
  HolidayUpdateRequest,
  SlaPolicy,
  SlaPolicyCreateRequest,
  SlaPolicyUpdateRequest,
  SlaPreview,
  SlaPreviewRequest,
} from './types'

const SLA_POLICIES_KEY = ['sla-policies', 'list']
const HOLIDAYS_KEY = ['holidays', 'list']

async function fetchSlaPolicies(): Promise<SlaPolicy[]> {
  const { data } = await apiClient.get<SlaPolicy[]>('/sla-policies')
  return data
}

async function createSlaPolicy(payload: SlaPolicyCreateRequest): Promise<SlaPolicy> {
  const { data } = await apiClient.post<SlaPolicy>('/sla-policies', payload)
  return data
}

async function updateSlaPolicy(
  policyId: string,
  payload: SlaPolicyUpdateRequest,
): Promise<SlaPolicy> {
  const { data } = await apiClient.patch<SlaPolicy>(`/sla-policies/${policyId}`, payload)
  return data
}

async function deleteSlaPolicy(policyId: string): Promise<void> {
  await apiClient.delete(`/sla-policies/${policyId}`)
}

async function previewSlaPolicy(payload: SlaPreviewRequest): Promise<SlaPreview> {
  const { data } = await apiClient.post<SlaPreview>('/sla-policies/preview', payload)
  return data
}

async function fetchHolidays(): Promise<Holiday[]> {
  const { data } = await apiClient.get<Holiday[]>('/holidays')
  return data
}

async function createHoliday(payload: HolidayCreateRequest): Promise<Holiday> {
  const { data } = await apiClient.post<Holiday>('/holidays', payload)
  return data
}

async function updateHoliday(holidayId: string, payload: HolidayUpdateRequest): Promise<Holiday> {
  const { data } = await apiClient.patch<Holiday>(`/holidays/${holidayId}`, payload)
  return data
}

async function deleteHoliday(holidayId: string): Promise<void> {
  await apiClient.delete(`/holidays/${holidayId}`)
}

/** Not paginated — like Roles & Permissions and Routing Rules, a
 * company's SLA policy count is small and meant to be seen as a whole. */
export function useSlaPoliciesQuery() {
  return useQuery({ queryKey: SLA_POLICIES_KEY, queryFn: fetchSlaPolicies })
}

function invalidateSlaPolicies(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: SLA_POLICIES_KEY })
}

export function useCreateSlaPolicyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createSlaPolicy,
    onSuccess: () => invalidateSlaPolicies(queryClient),
  })
}

export function useUpdateSlaPolicyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ policyId, payload }: { policyId: string; payload: SlaPolicyUpdateRequest }) =>
      updateSlaPolicy(policyId, payload),
    onSuccess: () => invalidateSlaPolicies(queryClient),
  })
}

export function useDeleteSlaPolicyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSlaPolicy,
    onSuccess: () => invalidateSlaPolicies(queryClient),
  })
}

export function usePreviewSlaPolicyMutation() {
  return useMutation({ mutationFn: previewSlaPolicy })
}

export function useHolidaysQuery() {
  return useQuery({ queryKey: HOLIDAYS_KEY, queryFn: fetchHolidays })
}

function invalidateHolidays(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: HOLIDAYS_KEY })
}

export function useCreateHolidayMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createHoliday,
    onSuccess: () => invalidateHolidays(queryClient),
  })
}

export function useUpdateHolidayMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ holidayId, payload }: { holidayId: string; payload: HolidayUpdateRequest }) =>
      updateHoliday(holidayId, payload),
    onSuccess: () => invalidateHolidays(queryClient),
  })
}

export function useDeleteHolidayMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteHoliday,
    onSuccess: () => invalidateHolidays(queryClient),
  })
}
