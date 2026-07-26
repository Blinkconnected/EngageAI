import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  ErpConfig,
  ErpConfigCreateRequest,
  ErpConfigUpdateRequest,
  ErpCustomerLink,
  ErpSyncedRecord,
  ErpTestConnectionRequest,
  ErpTestConnectionResult,
} from './types'

const ERP_CONFIGS_KEY = ['erp-configs']
const ERP_RECORDS_KEY = (customerId: string) => ['customers', customerId, 'erp-records']

async function fetchErpConfigs(params: PageParams): Promise<Page<ErpConfig>> {
  const { data } = await apiClient.get<Page<ErpConfig>>('/erp-configs', { params })
  return data
}

async function createErpConfig(payload: ErpConfigCreateRequest): Promise<ErpConfig> {
  const { data } = await apiClient.post<ErpConfig>('/erp-configs', payload)
  return data
}

async function updateErpConfig(
  erpConfigId: string,
  payload: ErpConfigUpdateRequest,
): Promise<ErpConfig> {
  const { data } = await apiClient.patch<ErpConfig>(`/erp-configs/${erpConfigId}`, payload)
  return data
}

async function deleteErpConfig(erpConfigId: string): Promise<void> {
  await apiClient.delete(`/erp-configs/${erpConfigId}`)
}

async function testErpConnectionEphemeral(
  payload: ErpTestConnectionRequest,
): Promise<ErpTestConnectionResult> {
  const { data } = await apiClient.post<ErpTestConnectionResult>(
    '/erp-configs/test-connection',
    payload,
  )
  return data
}

async function testErpConnection(erpConfigId: string): Promise<ErpTestConnectionResult> {
  const { data } = await apiClient.post<ErpTestConnectionResult>(
    `/erp-configs/${erpConfigId}/test-connection`,
  )
  return data
}

async function fetchErpRecords(customerId: string): Promise<ErpSyncedRecord[]> {
  const { data } = await apiClient.get<ErpSyncedRecord[]>(`/customers/${customerId}/erp-records`)
  return data
}

async function syncCustomerToErp(customerId: string): Promise<ErpCustomerLink> {
  const { data } = await apiClient.post<ErpCustomerLink>(`/customers/${customerId}/erp-sync`)
  return data
}

async function pullErpRecords(customerId: string, doctype: string): Promise<ErpSyncedRecord[]> {
  const { data } = await apiClient.post<ErpSyncedRecord[]>(
    `/customers/${customerId}/erp-pull/${encodeURIComponent(doctype)}`,
  )
  return data
}

export function useErpConfigsQuery(params: PageParams) {
  return useQuery({
    queryKey: [...ERP_CONFIGS_KEY, params],
    queryFn: () => fetchErpConfigs(params),
    placeholderData: (previousData) => previousData,
  })
}

export function useCreateErpConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createErpConfig,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ERP_CONFIGS_KEY }),
  })
}

export function useUpdateErpConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      erpConfigId,
      payload,
    }: {
      erpConfigId: string
      payload: ErpConfigUpdateRequest
    }) => updateErpConfig(erpConfigId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ERP_CONFIGS_KEY }),
  })
}

export function useDeleteErpConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteErpConfig,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ERP_CONFIGS_KEY }),
  })
}

/** Test connection details typed but not saved yet — the wizard/settings
 * "Test Connection" step. */
export function useTestErpConnectionEphemeralMutation() {
  return useMutation({ mutationFn: testErpConnectionEphemeral })
}

/** Re-check an already-saved ERP connection on demand. */
export function useTestErpConnectionMutation() {
  return useMutation({ mutationFn: testErpConnection })
}

export function useErpRecordsQuery(customerId: string) {
  return useQuery({
    queryKey: ERP_RECORDS_KEY(customerId),
    queryFn: () => fetchErpRecords(customerId),
  })
}

export function useSyncCustomerToErpMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => syncCustomerToErp(customerId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ERP_RECORDS_KEY(customerId) }),
  })
}

export function usePullErpRecordsMutation(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (doctype: string) => pullErpRecords(customerId, doctype),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ERP_RECORDS_KEY(customerId) }),
  })
}
