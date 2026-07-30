/**
 * The shapes `/api/v1/billing/*` returns.
 *
 * Every money field is a **string**, exactly as the API sends it. Nothing in
 * this feature parses one into a number: `parseFloat('0.035000') * 1200` is
 * how a UI ends up disagreeing with the invoice by a cent, and the whole
 * point of this page is that the two agree. Amounts are formatted for
 * display (see `money.ts`) and never used in arithmetic.
 */

export type ProjectionStrategy = 'daily_average' | 'rolling_7_day' | 'linear_pace'

export type ProjectionUnavailableReason =
  'no_complete_days' | 'too_early' | 'no_usage' | 'period_closed'

export type BillingStatus = 'active' | 'payment_due' | 'payment_overdue' | 'payment_suspended'

export type InvoiceStatus = 'draft' | 'issued' | 'paid' | 'overdue' | 'cancelled'

export type ChartWindow = '7d' | '30d' | 'period'

export interface MetricCost {
  metric_code: string
  display_name: string
  unit: string
  quantity: string
  unit_amount: string | null
  estimated_cost: string
  currency: string
  included_quantity: string
  billable_quantity: string
  /** Share of the period's estimated cost, 0–100. Computed server-side. */
  share_percent: string
}

export interface DayCost {
  day: string
  estimated_cost: string
  quantity: string
  currency: string
  /** A closed day. Rendered differently from today, which is still moving. */
  final: boolean
  projected_total_snapshot: string | null
}

export interface DailySeries {
  window: ChartWindow
  start: string
  end: string
  currency: string
  days: DayCost[]
  data_starts_on: string | null
  total_estimated_cost: string
}

export interface Projection {
  strategy: ProjectionStrategy
  /** What actually ran. Differs from `strategy` on fallback, and this is the
   * one that must be shown — naming the requested method when another one
   * ran is a small lie that costs a lot of trust. */
  effective_strategy: ProjectionStrategy | null
  fell_back: boolean
  method: string
  method_explanation: string
  projected_total: string | null
  actual_to_date: string
  daily_average: string | null
  days_measured: number
  days_elapsed: number
  days_in_period: number
  days_remaining: number
  currency: string
  unavailable_reason: ProjectionUnavailableReason | null
  unavailable_explanation: string | null
}

export interface TimelineEvent {
  key: string
  label: string
  at: string
  state: 'done' | 'current' | 'upcoming'
  detail: string | null
}

export interface PaymentMethod {
  code: string
  label: string
  available: boolean
  self_serve: boolean
  unavailable_reason: string | null
}

export interface InvoiceSummary {
  id: string
  invoice_number: string | null
  status: InvoiceStatus
  period_start: string
  period_end: string
  issued_at: string | null
  due_date: string | null
  total_amount: string
  amount_paid: string
  amount_credited: string
  amount_outstanding: string
  currency: string
  days_overdue: number
}

export interface BillingConfiguration {
  country_code: string | null
  country_name: string | null
  currency: string
  currency_symbol: string
  currency_decimal_places: number
  billing_model: string
  invoice_cadence: string
  payment_terms_days: number
  free_monthly_allowance: Record<string, string>
  auto_suspend_enabled: boolean
  suspend_after_days: number | null
  projection_strategy_default: ProjectionStrategy
}

export interface Tier {
  /** Inclusive upper bound; `null` is the open-ended top step. */
  up_to: string | null
  unit_amount: string
}

export interface MessageBreakdown {
  /** `channel`, `origin` or `direction`. */
  dimension: string
  /** `[label, message count]`, busiest first. Counts, never money: billing is
   * channel-agnostic, so a per-channel cost would be a number the invoice
   * does not contain. */
  rows: [string, number][]
  total: number
}

export interface UnitPrice {
  metric_code: string
  display_name: string
  unit: string
  unit_amount: string | null
  currency: string
  source: 'company' | 'profile' | 'global' | null
  effective_from: string | null
  free_allowance: string
  /** The volume table behind `unit_amount` — empty for a flat rate. A rate
   * that changes with volume is only checkable if the table is visible. */
  tiers: Tier[]
}

export type StatusDetailCode =
  | 'nothing_due'
  | 'invoice_due_on'
  | 'invoice_awaiting'
  | 'overdue'
  | 'overdue_document'
  | 'overdue_with_suspension'
  | 'suspended'

export interface BillingOverview {
  company_name: string
  currency: string
  currency_symbol: string
  currency_decimal_places: number
  billing_status: BillingStatus
  /** English, from the server. The fallback: prefer `status_detail_code`, so
   * an Arabic customer reads Arabic. */
  status_detail: string
  status_detail_code: StatusDetailCode
  status_detail_params: Record<string, string | number>
  period_start: string
  period_last_day: string
  days_elapsed: number
  days_remaining: number
  estimated_today: string
  estimated_month_to_date: string
  projected_total: string | null
  projection_method: string
  outstanding_balance: string
  credit_balance: string
  next_invoice_on: string
  next_payment_due_on: string
  no_open_period: boolean
}

export interface BillingEstimate {
  as_of: string
  currency: string
  estimated_today: string
  estimated_month_to_date: string
  today: MetricCost[]
  month_to_date: MetricCost[]
  projection: Projection
  data_as_of: string | null
}

export interface BillingDashboard {
  overview: BillingOverview
  estimate: BillingEstimate
  daily: DailySeries
  timeline: TimelineEvent[]
  invoices: InvoiceSummary[]
  payment_methods: PaymentMethod[]
  configuration: BillingConfiguration
  unit_prices: UnitPrice[]
  breakdowns: MessageBreakdown[]
  projection_alternatives: Projection[]
}

export interface InvoiceLine {
  metric_code: string
  description: string
  unit: string
  quantity: string
  included_quantity: string
  billable_quantity: string
  unit_amount: string
  currency: string
  subtotal: string
}

export interface InvoiceDetail {
  invoice: InvoiceSummary
  lines: InvoiceLine[]
}
