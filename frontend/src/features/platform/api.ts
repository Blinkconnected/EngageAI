import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type { CompanyOverview, CompanyStatus, FeatureState, PlatformProfile } from './types'

export const PLATFORM_ME_KEY = ['platform', 'me']
const COMPANIES_KEY = ['platform', 'companies']
const FEATURES_KEY = ['platform', 'features']

async function fetchPlatformMe(): Promise<PlatformProfile> {
  const { data } = await apiClient.get<PlatformProfile>('/platform/me')
  return data
}

/** Identifies the signed-in principal as a platform operator.
 *
 * `retry: false` matters: this is asked precisely when `/auth/me` has
 * already refused the token, so a 403 here is a real answer ("not a
 * platform admin either"), not a transient failure worth retrying — and
 * retrying would stall the sign-in redirect behind backoff. */
export function usePlatformMeQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: PLATFORM_ME_KEY,
    queryFn: fetchPlatformMe,
    enabled: options.enabled ?? true,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

export interface CompanyListParams {
  page: number
  page_size: number
  search?: string
  status_filter?: CompanyStatus
}

async function fetchCompanies(params: CompanyListParams): Promise<Page<CompanyOverview>> {
  const { data } = await apiClient.get<Page<CompanyOverview>>('/platform/companies', { params })
  return data
}

export function useCompaniesQuery(params: CompanyListParams) {
  return useQuery({
    queryKey: [...COMPANIES_KEY, params],
    queryFn: () => fetchCompanies(params),
  })
}

async function setCompanyStatus(input: {
  companyId: string
  status: CompanyStatus
  reason?: string
}): Promise<CompanyOverview> {
  const { data } = await apiClient.patch<CompanyOverview>(
    `/platform/companies/${input.companyId}/status`,
    { status: input.status, reason: input.reason ?? null },
  )
  return data
}

export function useSetCompanyStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setCompanyStatus,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COMPANIES_KEY })
    },
  })
}


// --- Feature entitlements -------------------------------------------

async function fetchFeatureCatalog(): Promise<FeatureState[]> {
  const { data } = await apiClient.get<FeatureState[]>('/platform/features')
  return data
}

export function useFeatureCatalogQuery() {
  return useQuery({ queryKey: FEATURES_KEY, queryFn: fetchFeatureCatalog, staleTime: Infinity })
}

async function fetchCompanyFeatures(companyId: string): Promise<FeatureState[]> {
  const { data } = await apiClient.get<FeatureState[]>(
    `/platform/companies/${companyId}/features`,
  )
  return data
}

export function useCompanyFeaturesQuery(companyId: string | null) {
  return useQuery({
    queryKey: [...COMPANIES_KEY, companyId, 'features'],
    queryFn: () => fetchCompanyFeatures(companyId as string),
    enabled: companyId !== null,
  })
}

async function setCompanyFeatures(input: {
  companyId: string
  overrides: Record<string, boolean>
}): Promise<FeatureState[]> {
  const { data } = await apiClient.put<FeatureState[]>(
    `/platform/companies/${input.companyId}/features`,
    { overrides: input.overrides },
  )
  return data
}

/** Replaces the whole override map. A PUT, not a PATCH: omitting a key
 * clears its override and returns that feature to following the plan,
 * which a merge could never express. */
export function useSetCompanyFeaturesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setCompanyFeatures,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COMPANIES_KEY })
    },
  })
}

