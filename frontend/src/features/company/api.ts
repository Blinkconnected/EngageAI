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

/** ERP is completely hidden from the UI (nav, routes, customer panels)
 * unless the company has explicitly enabled it — see
 * docs/architecture/company-onboarding.md. `false` while the company is
 * still loading, so nothing ERP-related flashes on screen before the
 * real value is known. */
export function useIsErpEnabled(): boolean {
  const companyQuery = useCompanyQuery()
  return companyQuery.data?.settings.erp?.enabled ?? false
}

/** Whether the Company Onboarding Wizard still has work left — gates the
 * post-registration redirect and the "Complete setup" banner. */
export function useIsOnboardingIncomplete(): boolean {
  const companyQuery = useCompanyQuery()
  if (!companyQuery.data) return false
  return !companyQuery.data.settings.onboarding?.completed
}
