export interface CompanySummary {
  id: string
  name: string
  slug: string
  /** Whether the signup owner has confirmed their email address. While
   * false the workspace can be read but not changed, so the UI shows a
   * banner and hides controls that would be refused — nobody should be
   * offered a button that cannot work. */
  verified: boolean
}

/** Matches the backend's `UserProfileResponse` (`GET /auth/me`, `POST /auth/register`). */
export interface UserProfile {
  id: string
  email: string
  full_name: string
  is_company_owner: boolean
  company: CompanySummary
  /** Product features this company is entitled to (its plan, plus any
   * per-company override a platform administrator has set — see
   * docs/architecture/billing.md). Carried on the profile because the
   * navigation needs it before the first screen renders. */
  features: string[]
  roles: string[]
  permissions: string[]
}
