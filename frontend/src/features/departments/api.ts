import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type { Department } from './types'

async function fetchAllDepartments(): Promise<Department[]> {
  const { data } = await apiClient.get<Page<Department>>('/departments', {
    params: { page: 1, page_size: 100 },
  })
  return data.items
}

/**
 * A full-list fetch (page_size=100), not a paginated view — used to
 * populate the department picker on the Agent form. A dedicated
 * Departments management page (create/edit/delete, real pagination) is
 * deferred to the secondary-pages polish milestone; organizations rarely
 * have more than a handful of departments, so this is proportionate for
 * now rather than premature.
 */
export function useAllDepartmentsQuery() {
  return useQuery({
    queryKey: ['departments', 'all'],
    queryFn: fetchAllDepartments,
    staleTime: 60_000,
  })
}
