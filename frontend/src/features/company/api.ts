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

async function uploadCompanyLogo(file: File): Promise<Company> {
  const formData = new FormData()
  formData.append('file', file)
  // Clearing the default JSON Content-Type lets axios generate the
  // correct `multipart/form-data; boundary=...` header itself — same
  // reasoning as conversations/api.ts's uploadAttachment.
  const { data } = await apiClient.post<Company>('/company/logo', formData, {
    headers: { 'Content-Type': undefined },
  })
  return data
}

async function deleteCompanyLogo(): Promise<Company> {
  const { data } = await apiClient.delete<Company>('/company/logo')
  return data
}

async function fetchCompanyLogoBlobUrl(): Promise<string> {
  const { data } = await apiClient.get<Blob>('/company/logo', { responseType: 'blob' })
  return URL.createObjectURL(data)
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

export function useUploadCompanyLogoMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: uploadCompanyLogo,
    onSuccess: (data) => queryClient.setQueryData(COMPANY_QUERY_KEY, data),
  })
}

export function useDeleteCompanyLogoMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCompanyLogo,
    onSuccess: (data) => queryClient.setQueryData(COMPANY_QUERY_KEY, data),
  })
}

/** Fetches the current logo as an authenticated blob (the storage bucket
 * isn't public-read, so a plain `<img src="/company/logo">` can't hit it
 * directly — same reasoning as conversations/api.ts's
 * fetchAttachmentBlobUrl), keyed by `logoKey` so replacing the logo gets
 * a fresh fetch under a new cache entry rather than serving a stale
 * blob. Never explicitly revoked — a company has at most one current
 * logo, replaced rarely, so the handful of stale object URLs left behind
 * over a session's lifetime is a negligible, bounded cost versus the
 * risk of revoking a blob URL still in use by another mounted consumer
 * (the topbar and Branding settings can both be showing it at once). */
export function useCompanyLogoUrl(logoKey: string | null | undefined) {
  return useQuery({
    queryKey: ['company', 'logo', logoKey],
    queryFn: fetchCompanyLogoBlobUrl,
    enabled: Boolean(logoKey),
    staleTime: Infinity,
    gcTime: Infinity,
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
