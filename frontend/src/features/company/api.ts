import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Company, CompanyUpdateRequest } from './types'

const COMPANY_QUERY_KEY = ['company']

async function fetchCompany(): Promise<Company> {
  const { data } = await apiClient.get<Company>('/company')
  return data
}

async function updateCompany(payload: CompanyUpdateRequest): Promise<Company> {
  const { data } = await apiClient.patch<Company>('/company', payload)
  return data
}

export function useCompanyQuery() {
  return useQuery({ queryKey: COMPANY_QUERY_KEY, queryFn: fetchCompany })
}

export function useUpdateCompanyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateCompany,
    onSuccess: (data) => {
      queryClient.setQueryData(COMPANY_QUERY_KEY, data)
    },
  })
}
