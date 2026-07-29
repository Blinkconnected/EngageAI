/** Matches the backend's `CompanyStatus`. */
export type CompanyStatus = 'trial' | 'active' | 'suspended'

/** Matches the backend's `PlatformProfileResponse` (`GET /platform/me`).
 * The counterpart to `/auth/me`, which refuses a platform token because
 * it describes a user *within a company* and a platform admin has none. */
export interface PlatformProfile {
  id: string
  email: string
  full_name: string
  is_platform_admin: boolean
}

/** Matches the backend's `CompanyOverviewResponse` — deliberately size
 * counts and lifecycle state only, never tenant content. */
export interface CompanyOverview {
  id: string
  name: string
  slug: string
  status: CompanyStatus
  created_at: string
  user_count: number
  agent_count: number
  conversation_count: number
}
