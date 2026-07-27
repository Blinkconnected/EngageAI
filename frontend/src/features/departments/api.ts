import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type { Department, DepartmentCreateRequest, DepartmentUpdateRequest } from './types'

const DEPARTMENTS_LIST_KEY = ['departments', 'list']

async function fetchDepartments(
  params: PageParams & { search?: string },
): Promise<Page<Department>> {
  const { data } = await apiClient.get<Page<Department>>('/departments', { params })
  return data
}

async function fetchAllDepartments(): Promise<Department[]> {
  const { data } = await apiClient.get<Page<Department>>('/departments', {
    params: { page: 1, page_size: 100 },
  })
  return data.items
}

async function createDepartment(payload: DepartmentCreateRequest): Promise<Department> {
  const { data } = await apiClient.post<Department>('/departments', payload)
  return data
}

async function updateDepartment(
  departmentId: string,
  payload: DepartmentUpdateRequest,
): Promise<Department> {
  const { data } = await apiClient.patch<Department>(`/departments/${departmentId}`, payload)
  return data
}

async function deleteDepartment(departmentId: string): Promise<void> {
  await apiClient.delete(`/departments/${departmentId}`)
}

export function useDepartmentsQuery(params: PageParams & { search?: string }) {
  return useQuery({
    queryKey: [...DEPARTMENTS_LIST_KEY, params],
    queryFn: () => fetchDepartments(params),
    placeholderData: (previousData) => previousData,
  })
}

/**
 * A full-list fetch (page_size=100), not a paginated view — used to
 * populate the department picker on the Agent form and to compute
 * per-department agent counts on the Departments page. Organizations
 * rarely have more than a handful of departments, so this is
 * proportionate rather than premature.
 */
export function useAllDepartmentsQuery() {
  return useQuery({
    queryKey: ['departments', 'all'],
    queryFn: fetchAllDepartments,
    staleTime: 60_000,
  })
}

function invalidateDepartments(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: DEPARTMENTS_LIST_KEY })
  queryClient.invalidateQueries({ queryKey: ['departments', 'all'] })
}

export function useCreateDepartmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDepartment,
    onSuccess: () => invalidateDepartments(queryClient),
  })
}

export function useUpdateDepartmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      departmentId,
      payload,
    }: {
      departmentId: string
      payload: DepartmentUpdateRequest
    }) => updateDepartment(departmentId, payload),
    onSuccess: () => invalidateDepartments(queryClient),
  })
}

export function useDeleteDepartmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDepartment,
    onSuccess: () => invalidateDepartments(queryClient),
  })
}
