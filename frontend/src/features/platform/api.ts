import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type {
  BillingPlan,
  CompanyOverview,
  CompanyStatus,
  FeatureState,
  PlatformProfile,
  Subscription,
} from './types'

export const PLATFORM_ME_KEY = ['platform', 'me']
const COMPANIES_KEY = ['platform', 'companies']
const PLANS_KEY = ['platform', 'plans']
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


// --- Billing catalog ------------------------------------------------

async function fetchPlans(): Promise<BillingPlan[]> {
  const { data } = await apiClient.get<BillingPlan[]>('/platform/plans')
  return data
}

/** Every plan, including withdrawn ones — an operator needs to see what
 * they have retired, not only what is on sale. */
export function usePlatformPlansQuery() {
  return useQuery({ queryKey: PLANS_KEY, queryFn: fetchPlans })
}

export interface CreatePlanInput {
  name: string
  description?: string | null
  amount: string
  currency: string
  interval: 'month' | 'year'
  features: string[] | null
}

async function createPlan(input: CreatePlanInput): Promise<BillingPlan> {
  const { data } = await apiClient.post<BillingPlan>('/platform/plans', input)
  return data
}

export function useCreatePlanMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createPlan,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PLANS_KEY })
    },
  })
}

async function setPlanStatus(input: { planId: string; isActive: boolean }): Promise<BillingPlan> {
  const { data } = await apiClient.patch<BillingPlan>(
    `/platform/plans/${input.planId}/status`,
    { is_active: input.isActive },
  )
  return data
}

export function useSetPlanStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setPlanStatus,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PLANS_KEY })
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

async function fetchCompanySubscription(companyId: string): Promise<Subscription | null> {
  const { data } = await apiClient.get<Subscription | null>(
    `/platform/companies/${companyId}/subscription`,
  )
  return data
}

export function useCompanySubscriptionQuery(companyId: string | null) {
  return useQuery({
    queryKey: [...COMPANIES_KEY, companyId, 'subscription'],
    queryFn: () => fetchCompanySubscription(companyId as string),
    enabled: companyId !== null,
  })
}
