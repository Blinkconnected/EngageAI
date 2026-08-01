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

export type MeasurementUnit =
  | 'message'
  | 'conversation'
  | 'reply'
  | 'token'
  | 'image'
  | 'character'
  | 'minute'
  | 'gigabyte'
  | 'gigabyte_month'
  | 'request'
  | 'event'
  | 'email'
  | 'notification'
  | 'agent_month'
  | 'bot_month'
  | 'unit'

/** How a period's usage is derived from what was measured. Not a label — it
 * decides the arithmetic, and a seat totalled like a message bills thirty
 * times the seats. */
export type MetricKind = 'counter' | 'continuous' | 'sampled' | 'seat'

/** Whether a meter exists today. Only `measured` may be priced. */
export type MetricAvailability = 'measured' | 'planned' | 'retired'

/** How a rate turns usage into money. */
export type PricingModel =
  'flat' | 'volume_tier' | 'graduated_tier' | 'package' | 'fixed_fee' | 'committed' | 'subscription'

/** One step of a tier table. `up_to` is inclusive; `null` is the open-ended
 * top step, and every table needs exactly one. */
export interface Tier {
  up_to: string | null
  unit_amount: string
}

/** Matches `PricingModelInfoResponse`.
 *
 * `enabled` is the product decision — what may be written today. `implemented`
 * says the arithmetic exists. Both are sent so a console can show what is
 * coming without offering it, and so this screen needs no change the day one
 * is turned on. */
export interface PricingModelInfo {
  model: PricingModel
  display_name: string
  description: string
  enabled: boolean
  implemented: boolean
  requires_tiers: boolean
}

/** Matches `BillableMetricResponse`. Read-only: metrics are code, not
 * configuration — `is_priceable` is false for a metric nothing measures
 * yet, and the API refuses to price those. */
export interface BillableMetric {
  code: string
  display_name: string
  unit: MeasurementUnit
  description: string
  kind: MetricKind
  availability: MetricAvailability
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
  /** Which price list this is. Nothing converts, so a metric has one rate per
   * currency and all of them are in force at once — the list only means
   * something once you know which one you are reading. */
  currency: string
  /** The other lists that can be asked for. Sent by the server so the console
   * never keeps its own copy of the currency table. */
  available_currencies: string[]
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

/** What a rate's terms cost at a given quantity — computed **server-side**.
 *
 * The console never multiplies a rate by a quantity itself: a tier table has
 * to be applied the same way the invoice applies it, and a second
 * implementation in TypeScript is how a preview ends up disagreeing with a
 * bill. See `useQuotePricingMutation`. */
export interface PricingQuote {
  model: PricingModel
  quantity: string
  included_quantity: string
  billable_quantity: string
  unit_amount: string
  tier_up_to: string | null
  tier_index: number
  subtotal: string
  currency: string
  minimum_applied: boolean
}

export interface PricingRate {
  id: string
  scope: PricingScope
  metric_code: string
  company_id: string | null
  profile_id: string | null
  pricing_model: string
  unit_amount: string
  included_quantity: string | null
  minimum_charge: string | null
  tiers: Tier[]
  currency: string
  effective_from: string
  effective_until: string | null
  voided_at: string | null
  created_by_email: string | null
  reason: string | null
}

/** How a customer actually pays. The distinction the screen is built on:
 * `redirect` sends them to a hosted checkout, `bill_presentment` publishes
 * a bill they pay at their own bank, `credit_transfer` is money they push
 * to an alias, and `operator_entry` is finance recording what arrived. */
export type PaymentFlow =
  | 'redirect'
  | 'bill_presentment'
  | 'credit_transfer'
  | 'operator_entry'

/** `awaiting_integration` means credentials can be stored but no adapter
 * exists yet — shown plainly rather than as a button that cannot work. */
export type ProviderReadiness = 'active' | 'not_configured' | 'awaiting_integration'

export interface CredentialField {
  name: string
  label: string
  secret: boolean
  required: boolean
  help_text: string | null
  choices: string[]
}

export interface PaymentProvider {
  kind: string
  label: string
  description: string
  flow: PaymentFlow
  /** ISO 3166-1 alpha-2 codes this provider serves; empty means everywhere. */
  countries: string[]
  /** The form, described by the backend so a required field cannot be one
   * this screen never renders. */
  fields: CredentialField[]
  enabled: boolean
  readiness: ProviderReadiness
  /** Required fields with nothing in them, so the screen can point at the
   * empty box rather than saying "invalid". */
  missing: string[]
  /** Which secrets have a value — never the values. */
  secret_set: Record<string, boolean>
  /** Everything that is not a secret. */
  values: Record<string, unknown>
  pending_note: string | null
}

export interface PaymentProvidersResponse {
  providers: PaymentProvider[]
  updated_by_email: string | null
  updated_at: string | null
}

export interface PaymentProviderInput {
  enabled: boolean
  /** A secret omitted keeps what is stored; an empty string clears it. The
   * screen is never given a stored secret, so it must not send one back. */
  values: Record<string, unknown>
}

export interface SchedulerMetric {
  key: string
  /** The human name, sent by the backend so a counter added to a task shows
   * with a proper name rather than as a raw key. */
  label: string
  value: number
}

export interface SchedulerRun {
  status: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  metrics: SchedulerMetric[]
  /** Items this run could not process — distinct from the run failing. */
  failures: number
  error: string | null
  attempt: number
}

export interface SchedulerTaskHealth {
  name: string
  label: string
  description: string
  /** `healthy` | `degraded` | `failing` | `never_run`. */
  health: string
  interval_seconds: number
  last_run: SchedulerRun | null
  last_success: SchedulerRun | null
  next_run_at: string | null
  consecutive_failures: number
}

export interface SchedulerHealth {
  health: string
  tasks: SchedulerTaskHealth[]
  evaluated_at: string
}
