import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type {
  BillableMetric,
  CompanyOverview,
  CompanyStatus,
  EffectivePricing,
  FeatureState,
  PlatformProfile,
  PricingAuditEntry,
  PricingHealth,
  PricingProfile,
} from './types'
import type {
  PricingRate,
  ResolveUsagePriceResponse,
  SetCompanyRateInput,
  MailSettings,
  MailSettingsInput,
  TestMailResult,
} from './types'

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


// --- Pricing engine ---------------------------------------------------

const PRICING_KEY = ['platform', 'pricing']

async function fetchMetrics(): Promise<BillableMetric[]> {
  const { data } = await apiClient.get<BillableMetric[]>('/platform/pricing/metrics')
  return data
}

/** The catalog never changes at runtime — metrics are code — so this is
 * cached for the session rather than refetched. */
export function useBillableMetricsQuery() {
  return useQuery({ queryKey: [...PRICING_KEY, 'metrics'], queryFn: fetchMetrics, staleTime: Infinity })
}

async function fetchPricingProfiles(): Promise<PricingProfile[]> {
  const { data } = await apiClient.get<PricingProfile[]>('/platform/pricing/profiles')
  return data
}

export function usePricingProfilesQuery() {
  return useQuery({ queryKey: [...PRICING_KEY, 'profiles'], queryFn: fetchPricingProfiles })
}

async function fetchEffectivePricing(params: {
  companyId?: string
  profileId?: string
}): Promise<EffectivePricing> {
  const { data } = await apiClient.get<EffectivePricing>('/platform/pricing/effective', {
    params: { company_id: params.companyId, profile_id: params.profileId },
  })
  return data
}

export function useEffectivePricingQuery(params: { companyId?: string; profileId?: string } = {}) {
  return useQuery({
    queryKey: [...PRICING_KEY, 'effective', params],
    queryFn: () => fetchEffectivePricing(params),
  })
}

async function fetchPricingHealth(): Promise<PricingHealth> {
  const { data } = await apiClient.get<PricingHealth>('/platform/pricing/health')
  return data
}

export function usePricingHealthQuery() {
  return useQuery({ queryKey: [...PRICING_KEY, 'health'], queryFn: fetchPricingHealth })
}

async function fetchPricingHistory(params: {
  metricCode?: string
  companyId?: string
}): Promise<PricingAuditEntry[]> {
  const { data } = await apiClient.get<PricingAuditEntry[]>('/platform/pricing/history', {
    params: { metric_code: params.metricCode, company_id: params.companyId },
  })
  return data
}

export function usePricingHistoryQuery(params: { metricCode?: string; companyId?: string } = {}) {
  return useQuery({
    queryKey: [...PRICING_KEY, 'history', params],
    queryFn: () => fetchPricingHistory(params),
  })
}

export interface SetPriceInput {
  /** Omit both for the global default; set one for a profile or company. */
  companyId?: string
  profileId?: string
  metricCode: string
  unitAmount: string
  effectiveFrom: string
  reason?: string
  /** Optimistic concurrency — without one of these two, a second
   * operator's edit silently overwrites the first. */
  expectedCurrentRateId?: string
  expectNoCurrentRate?: boolean
}

async function setPrice(input: SetPriceInput) {
  const path = input.companyId
    ? `/platform/pricing/companies/${input.companyId}/metrics/${input.metricCode}`
    : input.profileId
      ? `/platform/pricing/profiles/${input.profileId}/metrics/${input.metricCode}`
      : `/platform/pricing/global/metrics/${input.metricCode}`
  const { data } = await apiClient.put(path, {
    unit_amount: input.unitAmount,
    effective_from: input.effectiveFrom,
    reason: input.reason ?? null,
    ...(input.expectedCurrentRateId
      ? { expected_current_rate_id: input.expectedCurrentRateId }
      : { expect_no_current_rate: input.expectNoCurrentRate ?? false }),
  })
  return data
}

export function useSetPriceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setPrice,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PRICING_KEY })
    },
  })
}

async function assignPricingProfile(input: {
  companyId: string
  profileId: string | null
  effectiveFrom: string
  reason?: string
}) {
  await apiClient.put(`/platform/pricing/companies/${input.companyId}/profile`, {
    profile_id: input.profileId,
    effective_from: input.effectiveFrom,
    reason: input.reason ?? null,
  })
}

export function useAssignPricingProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: assignPricingProfile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PRICING_KEY })
    },
  })
}

const MAIL_SETTINGS_KEY = ['platform', 'settings', 'mail']

async function fetchMailSettings(): Promise<MailSettings> {
  const { data } = await apiClient.get<MailSettings>('/platform/settings/mail')
  return data
}

export function useMailSettingsQuery() {
  return useQuery({ queryKey: MAIL_SETTINGS_KEY, queryFn: fetchMailSettings })
}

export function useSaveMailSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: MailSettingsInput) => {
      const { data } = await apiClient.put<MailSettings>('/platform/settings/mail', input)
      return data
    },
    // Seed the cache from the response rather than invalidating: the
    // PUT already returns the resolved settings, and a refetch would
    // briefly render the previous values over the ones just saved.
    onSuccess: (data) => queryClient.setQueryData(MAIL_SETTINGS_KEY, data),
  })
}

export function useResetMailSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.delete<MailSettings>('/platform/settings/mail')
      return data
    },
    onSuccess: (data) => queryClient.setQueryData(MAIL_SETTINGS_KEY, data),
  })
}

export function useTestMailMutation() {
  return useMutation({
    mutationFn: async (toAddress: string) => {
      const { data } = await apiClient.post<TestMailResult>('/platform/settings/mail/test', {
        to_address: toAddress,
      })
      return data
    },
  })
}

// --- Company pricing -------------------------------------------------
//
// Every price shown by the console comes from one of these calls. The UI
// deliberately never picks a winner between scopes, never multiplies, and
// never formats an amount it computed itself: precedence is the Pricing
// Resolver's job, and a second implementation in TypeScript would drift
// from it silently. See docs/architecture/billing.md.

const companyPricingKey = (companyId: string) => ['platform', 'pricing', 'company', companyId]

export function useCompanyEffectivePricingQuery(companyId: string, at?: string) {
  return useQuery({
    queryKey: [...companyPricingKey(companyId), 'effective', at ?? 'now'],
    queryFn: async () => {
      const { data } = await apiClient.get<EffectivePricing>('/platform/pricing/effective', {
        params: { company_id: companyId, ...(at ? { at } : {}) },
      })
      return data
    },
  })
}

/** The resolver's own answer for one metric at one instant.
 *
 * A POST, but a read: it is the preview, and it writes nothing. Used
 * rather than reasoning from the effective-pricing table because the
 * point of a preview is to ask the resolver, not to model it. */
export function useResolvePriceMutation() {
  return useMutation({
    mutationFn: async (input: { companyId: string; metricCode: string; at: string }) => {
      // The resolver is a *batch* endpoint — it is built for rating a
      // whole period — so a preview is a batch of one.
      //
      // `strict: false` on purpose: "no price is configured for this at
      // that moment" is a real answer an operator needs to see, not an
      // error. It comes back in `unpriced` with the resolver's own reason.
      const { data } = await apiClient.post<ResolveUsagePriceResponse>(
        '/platform/pricing/resolve',
        {
          items: [
            {
              company_id: input.companyId,
              metric_code: input.metricCode,
              occurred_at: input.at,
            },
          ],
          strict: false,
        },
      )
      return data
    },
  })
}

export function useCompanyRatesQuery(companyId: string, metricCode?: string) {
  return useQuery({
    queryKey: [...companyPricingKey(companyId), 'rates', metricCode ?? 'all'],
    enabled: Boolean(metricCode),
    queryFn: async () => {
      const { data } = await apiClient.get<PricingRate[]>('/platform/pricing/rates', {
        params: { scope: 'company', company_id: companyId, metric_code: metricCode },
      })
      return data
    },
  })
}

export function useCompanyPricingHistoryQuery(companyId: string) {
  return useQuery({
    queryKey: [...companyPricingKey(companyId), 'history'],
    queryFn: async () => {
      const { data } = await apiClient.get<PricingAuditEntry[]>('/platform/pricing/history', {
        params: { company_id: companyId, limit: 100 },
      })
      return data
    },
  })
}

export function useSetCompanyRateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ companyId, metricCode, ...body }: SetCompanyRateInput) => {
      const { data } = await apiClient.put(
        `/platform/pricing/companies/${companyId}/metrics/${metricCode}`,
        body,
      )
      return data
    },
    // Invalidated rather than seeded from the response: a company
    // override can be *shadowed* by nothing, but its effect on the
    // resolved table depends on profile assignment and effective dates,
    // so the authoritative answer has to come back from the resolver.
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: companyPricingKey(variables.companyId) }),
  })
}

export function useEndCompanyRateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      companyId: string
      metricCode: string
      effective_from: string
      reason: string
      expected_current_rate_id?: string | null
    }) => {
      const { companyId, metricCode, ...body } = input
      await apiClient.post(
        `/platform/pricing/companies/${companyId}/metrics/${metricCode}/end`,
        body,
      )
    },
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: companyPricingKey(variables.companyId) }),
  })
}

export function useAssignProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      companyId: string
      profile_id: string | null
      effective_from: string
      reason: string
    }) => {
      const { companyId, ...body } = input
      await apiClient.put(`/platform/pricing/companies/${companyId}/profile`, body)
    },
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: companyPricingKey(variables.companyId) }),
  })
}
