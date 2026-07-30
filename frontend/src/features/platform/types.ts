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
  /** True when this operator may read but not change. The console
   * disables its controls and says so — the server enforces it too,
   * because a disabled button is a courtesy, not a permission. */
  read_only?: boolean
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

/** What the Pricing Resolver decided for one metric at one instant.
 *
 * Mirrors `ResolvedPriceResponse`. This is the *resolver's own answer* —
 * the console renders it verbatim and never derives a price itself, so
 * what an operator previews is exactly what a closing period will use. */
export interface ResolvedUsagePrice {
  company_id: string
  metric_code: string
  occurred_at: string
  unit_amount: string
  currency: string
  scope: PricingScope
  rate_id: string
  quantity: string | null
  amount: string | null
}

export interface UnpricedItem {
  company_id: string
  metric_code: string
  occurred_at: string
  /** The resolver's own explanation. Shown verbatim: it says *why* no
   * price applied, which is the useful part. */
  reason: string
}

/** The resolver's answer. A batch endpoint — it is built for rating a
 * whole period — so a preview is a batch of one. */
export interface ResolveUsagePriceResponse {
  priced: ResolvedUsagePrice[]
  unpriced: UnpricedItem[]
}

export interface SetCompanyRateInput {
  companyId: string
  metricCode: string
  unit_amount: string
  effective_from: string
  effective_until?: string | null
  reason: string
  currency: string
  /** Optimistic concurrency. Without one of these two, two operators
   * editing the same price both succeed and the second silently
   * overwrites the first. */
  expected_current_rate_id?: string | null
  expect_no_current_rate?: boolean
  allow_backdating?: boolean
}

export interface PricingRate {
  id: string
  scope: PricingScope
  metric_code: string
  company_id: string | null
  profile_id: string | null
  unit_amount: string
  currency: string
  effective_from: string
  effective_until: string | null
  voided_at: string | null
  created_by_email: string | null
  reason: string | null
}
