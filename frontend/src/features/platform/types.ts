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
  /** Billing state, so the grid can answer "who is actually paying?"
   * without a request per row. Both null for a company that has never
   * subscribed. */
  plan_name: string | null
  subscription_status: SubscriptionStatus | null
}

/** Matches the backend's `SubscriptionStatus`, which deliberately
 * mirrors PayPal's own vocabulary rather than inventing a parallel one. */
export type SubscriptionStatus =
  | 'approval_pending'
  | 'active'
  | 'past_due'
  | 'suspended'
  | 'cancelled'
  | 'expired'

export type BillingInterval = 'month' | 'year'

/** Matches the backend's `BillingPlanResponse`. `features: null` means
 * the plan grants everything — deliberately distinct from `[]`, which
 * grants nothing. */
export interface BillingPlan {
  id: string
  name: string
  description: string | null
  amount: string
  currency: string
  interval: BillingInterval
  is_active: boolean
  sort_order: number
  features: string[] | null
  is_purchasable: boolean
}

/** Matches the backend's `FeatureStateResponse`. `source` tells an
 * operator *why* a feature is off, which decides how they fix it. */
export interface FeatureState {
  key: string
  name: string
  description: string
  enabled: boolean
  source: 'override' | 'plan' | 'default'
}

export interface Subscription {
  id: string
  company_id: string
  plan_id: string
  plan_name: string
  amount: string
  currency: string
  interval: BillingInterval
  status: SubscriptionStatus
  approval_url: string | null
  current_period_end: string | null
  started_at: string | null
  cancelled_at: string | null
  failed_payment_count: number
}
