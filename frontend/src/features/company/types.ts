export type CompanyStatus = 'trial' | 'active' | 'suspended'

/** Matches the backend's `CompanyResponse` (`GET`/`PATCH /company`). */
export interface Company {
  id: string
  name: string
  slug: string
  status: CompanyStatus
  settings: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CompanyUpdateRequest {
  name?: string
}
