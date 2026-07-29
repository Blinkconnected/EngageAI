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

/** Matches the backend's `FeatureStateResponse`. `source` tells an
 * operator *why* a feature is off, which decides how they fix it. */
export interface FeatureState {
  key: string
  name: string
  description: string
  enabled: boolean
  source: 'override' | 'plan' | 'default'
}

// --- Pricing engine ---------------------------------------------------

/** Matches the backend's `PricingScope`. Company beats profile beats
 * global — the precedence lives in the backend, never re-derived here. */
export type PricingScope = 'company' | 'profile' | 'global'

export type MeasurementUnit = 'conversation' | 'reply' | 'minute' | 'gigabyte_month'

/** Matches `BillableMetricResponse`. Read-only: metrics are code, not
 * configuration — `is_priceable` is false for a metric nothing measures
 * yet, and the API refuses to price those. */
export interface BillableMetric {
  code: string
  display_name: string
  unit: MeasurementUnit
  description: string
  is_priceable: boolean
}

export interface PricingProfile {
  id: string
  key: string
  name: string
  description: string | null
  is_system: boolean
  is_active: boolean
  sort_order: number
}

export interface ShadowedPrice {
  scope: PricingScope
  unit_amount: string
  rate_id: string
  profile_id: string | null
}

/** One row of the pricing table. `unit_amount === null` means no price is
 * configured anywhere — a gap that is shown, not hidden. All amounts are
 * strings: a JSON number would become a float and reintroduce drift. */
export interface EffectivePrice {
  metric_code: string
  display_name: string
  unit: MeasurementUnit
  unit_amount: string | null
  currency: string | null
  scope: PricingScope | null
  rate_id: string | null
  effective_from: string | null
  effective_until: string | null
  shadowed: ShadowedPrice[]
}

export interface EffectivePricing {
  resolved_at: string
  company_id: string | null
  profile_id: string | null
  profile_name: string | null
  currency: string
  items: EffectivePrice[]
}

export interface PricingAuditEntry {
  id: string
  action: string
  scope: PricingScope | null
  metric_code: string | null
  company_id: string | null
  profile_id: string | null
  old_unit_amount: string | null
  new_unit_amount: string | null
  currency: string | null
  effective_from: string | null
  changed_by_email: string | null
  changed_by_name: string | null
  reason: string | null
  occurred_at: string
}

export interface MetricCoverage {
  metric_code: string
  display_name: string
  covered: boolean
  reason: string | null
}

export interface PricingHealth {
  ok: boolean
  metrics: MetricCoverage[]
}

/** How the connection to the outbound mail relay is protected.
 *
 * Three values rather than a pair of booleans: `useTls` and `startTls`
 * as separate flags admit a combination that means nothing (both true)
 * and one that silently sends credentials in clear (both false). */
export type MailSecurity = 'tls' | 'starttls' | 'none'

export interface MailSettings {
  host: string
  port: number
  security: MailSecurity
  from_address: string
  from_name: string
  username: string | null
  /** Whether *a* password is configured. The password itself is never
   * sent back — a blank field would otherwise mean both "no
   * authentication" and "authenticated, but hidden". */
  password_set: boolean
  timeout_seconds: number
  /** False when these values come from environment variables. */
  customised: boolean
  updated_by_email: string | null
  updated_at: string | null
}

export interface MailSettingsInput {
  host: string
  port: number
  security: MailSecurity
  from_address: string
  from_name: string
  username: string | null
  /** Omit to keep the stored password; send an empty string to clear it. */
  password?: string | null
  timeout_seconds: number
}

export interface TestMailResult {
  delivered: boolean
  /** The relay's own words when it refused. */
  detail: string | null
}
