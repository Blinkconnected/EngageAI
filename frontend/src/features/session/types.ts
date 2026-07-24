export interface CompanySummary {
  id: string
  name: string
  slug: string
}

/** Matches the backend's `UserProfileResponse` (`GET /auth/me`, `POST /auth/register`). */
export interface UserProfile {
  id: string
  email: string
  full_name: string
  is_company_owner: boolean
  company: CompanySummary
  roles: string[]
  permissions: string[]
}
