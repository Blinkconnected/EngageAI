/**
 * What the Billing Console reads.
 *
 * Every amount is a `string`, deliberately, all the way from the `NUMERIC`
 * column to the cell it is rendered in. A JSON number becomes a float in the
 * browser and reintroduces exactly the drift `Decimal` exists to prevent —
 * and a finance console that displays a figure a hundredth off the invoice is
 * worse than one that displays nothing.
 *
 * Notice the shape of every collection here: **grouped by currency, with no
 * field above the grouping to hold a total.** Blink Engage bills in dollars
 * and dinars, nothing converts between them, and no exchange rate is stored
 * anywhere on purpose. The API makes a cross-currency sum impossible rather
 * than merely unwise, and these types carry that guarantee into the UI.
 */

export type InvoiceStatus = 'draft' | 'issued' | 'paid' | 'overdue' | 'cancelled'

export type BillingStatus =
  | 'active'
  | 'payment_due'
  | 'payment_overdue'
  | 'payment_suspended'

export type AgingBucketKey =
  | 'current'
  | 'days_1_30'
  | 'days_31_60'
  | 'days_61_90'
  | 'days_90_plus'

export type LedgerAccount =
  | 'accounts_receivable'
  | 'cash'
  | 'customer_credit'
  | 'revenue'
  | 'revenue_adjustments'
  | 'bad_debt'

export type LedgerEntryType =
  | 'invoice.issued'
  | 'invoice.cancelled'
  | 'credit_note.issued'
  | 'payment.received'
  | 'payment.allocated'
  | 'payment.allocation_reversed'
  | 'payment.refunded'
  | 'payment.chargeback'
  | 'receivable.written_off'
  | 'adjustment.manual'

export type RunRateMethod =
  | 'trailing_30_day'
  | 'scaled_from_window'
  | 'insufficient_history'

// --- Revenue ---------------------------------------------------------

export interface RunRate {
  amount: string
  currency: string
  /** Always rendered beside the amount. There are no subscriptions to
   * contract, so this figure is a derivation and must say which one. */
  method: RunRateMethod
  days_observed: number
  is_meaningful: boolean
}

export interface CurrencyRevenue {
  currency: string
  /** Recognised in the window. */
  revenue: string
  /** Owed right now, across all time — a position, not a period figure. */
  outstanding: string
  customer_credit: string
  bad_debt: string
  /** Cash received in the window, net of refunds. */
  collected: string
  run_rate: RunRate
  /** `null` when nothing was billed: undefined, not zero. May exceed 1 when
   * the window collected arrears billed before it. */
  collection_ratio: string | null
}

export interface RevenueOverview {
  period_from: string
  period_to: string
  currencies: CurrencyRevenue[]
  companies_behind: number
  companies_suspended: number
  as_of: string
}

// --- Invoices --------------------------------------------------------

export interface Invoice {
  id: string
  company_id: string
  billing_period_id: string
  invoice_number: string | null
  status: InvoiceStatus
  customer_name: string
  customer_slug: string
  period_start: string
  period_end: string
  subtotal_amount: string
  total_amount: string
  currency: string
  amount_paid: string
  amount_credited: string
  issued_at: string | null
  due_date: string | null
  paid_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  /** When the receivable was abandoned as uncollectable. A timestamp
   * rather than a status: the invoice stays overdue and unpaid, which is
   * true — what changed is that nobody is chasing it. */
  written_off_at: string | null
}

export interface InvoiceLine {
  id: string
  metric_code: string
  metric_version: number
  description: string
  unit: string
  quantity: string
  /** Covered by the free allowance. `quantity - included = billable`, and
   * showing all three is why a customer can see why they were charged for
   * 50 of the 150 they used. */
  included_quantity: string
  billable_quantity: string
  unit_amount: string
  currency: string
  subtotal: string
  /** The rate row that priced this line. Its presence is what makes the
   * invoice reproducible from the historical rate tables. */
  rate_id: string | null
  usage_period_line_id: string | null
}

export interface CreditNote {
  id: string
  invoice_id: string
  credit_note_number: string
  customer_name: string
  subtotal_amount: string
  total_amount: string
  currency: string
  reason: string
  issued_at: string
}

export interface CreditNoteLineInput {
  description: string
  quantity: string
  unit_amount: string
  invoice_line_id?: string
}

export interface IssueCreditNoteInput {
  lines: CreditNoteLineInput[]
  reason: string
}

export interface InvoiceDetail {
  invoice: Invoice
  lines: InvoiceLine[]
  credit_notes: CreditNote[]
  /** What is still owed, as the engine defines it — zero for a draft, a
   * withdrawn document or a written-off debt, none of which anybody is
   * chasing. Sent rather than derived here so every screen agrees. */
  amount_outstanding: string
}

export interface InvoiceSearchGroup {
  currency: string
  invoice_count: number
  total_amount: string
  amount_paid: string
  amount_credited: string
  amount_outstanding: string
  items: Invoice[]
}

export interface InvoiceSearchResult {
  total: number
  limit: number
  offset: number
  currencies: InvoiceSearchGroup[]
  /** The most rows an export will write. Shown before the download so a
   * truncated file is never mistaken for a complete one. */
  export_row_cap: number
}

export interface InvoiceSearchParams {
  company_id?: string
  status?: InvoiceStatus
  currency?: string
  issued_from?: string
  issued_to?: string
  q?: string
  limit?: number
  offset?: number
}

// --- Payments --------------------------------------------------------

export interface Payment {
  id: string
  company_id: string
  amount: string
  currency: string
  received_at: string
  provider: string | null
  reference: string | null
  note: string | null
}

export interface PaymentAllocation {
  id: string
  payment_id: string
  payment_reference: string | null
  invoice_id: string
  invoice_number: string | null
  amount: string
  currency: string
  allocated_at: string
  reversed: boolean
  reversed_at: string | null
  reversal_reason: string | null
}

export interface AllocationGroup {
  currency: string
  matching: number
  allocated_total: string
  reversed_total: string
  allocations: PaymentAllocation[]
}

export interface AllocationPage {
  total: number
  limit: number
  offset: number
  currencies: AllocationGroup[]
}

export interface RecordPaymentInput {
  company_id: string
  amount: string
  /** Required. A payment with no date cannot be aged, allocated in order,
   * or reconciled against a bank statement. */
  received_at: string
  reference?: string
  note?: string
}

export interface AllocatePaymentInput {
  invoice_id: string
  amount: string
}

export interface Refund {
  id: string
  payment_id: string
  company_id: string
  provider: string
  provider_reference: string | null
  status: string
  amount: string
  currency: string
  reason: string
  failure_reason: string | null
  created_at: string
  completed_at: string | null
}

export interface RefundableAmount {
  payment_id: string
  /** What is still refundable, after refunds already issued. The server
   * works it out; the console never subtracts one amount from another. */
  refundable: string
  currency: string
}

// --- Ledger ----------------------------------------------------------

export interface LedgerEntry {
  id: string
  entry_number: number
  occurred_at: string
  company_id: string | null
  entry_type: LedgerEntryType
  debit_account: LedgerAccount
  credit_account: LedgerAccount
  amount: string
  currency: string
  reference_entity: string
  reference_id: string | null
  reference_number: string | null
  correlation_id: string | null
  description: string
  /** True when the entry was rebuilt from history rather than written at
   * the time. Shown, because a reconstructed line is weaker evidence. */
  reconstructed: boolean
}

export interface LedgerStatementRow {
  entry: LedgerEntry
  /** Exactly one of these is set — which side an entry lands on depends on
   * the account being viewed, and the server decides it. */
  debit: string | null
  credit: string | null
  balance: string
}

export interface LedgerStatement {
  company_id: string
  account: LedgerAccount
  currency: string
  available_currencies: string[]
  since: string | null
  until: string | null
  /** Where the account stood before the period began. */
  opening_balance: string
  /** Where it stood before *this page* began — so a running balance on
   * page 3 still reconciles. */
  page_opening_balance: string
  closing_balance: string
  rows: LedgerStatementRow[]
  total: number
  limit: number
  offset: number
}

export interface TrialBalanceAccount {
  account: LedgerAccount
  debits: string
  credits: string
  balance: string
}

export interface TrialBalance {
  currency: string
  accounts: TrialBalanceAccount[]
  total_debits: string
  total_credits: string
  entry_count: number
  /** Debits equal credits. Answered by the server rather than compared
   * here: two strings that look equal in JavaScript are not proof. */
  in_balance: boolean
}

// --- Collections -----------------------------------------------------

export interface AgingBucket {
  bucket: AgingBucketKey
  from_days: number | null
  to_days: number | null
  invoice_count: number
  amount_outstanding: string
}

export interface CurrencyAging {
  currency: string
  buckets: AgingBucket[]
  invoice_count: number
  total_outstanding: string
}

export interface AgingReport {
  as_of: string
  currencies: CurrencyAging[]
}

export interface CompanyStanding {
  company_id: string
  company_name: string
  /** This company's billing currency. On every row because the list spans
   * companies billing in different ones, and `amount_outstanding` must
   * never be added across them. */
  currency: string
  billing_status: BillingStatus
  billing_suspended_at: string | null
  /** Set on a company that must never be auto-suspended — a government
   * tenant, say — so the sweep skips it and a human decides. */
  never_auto_suspend: boolean
  open_invoices: number
  overdue_invoices: number
  amount_outstanding: string
  next_action_on: string | null
}

export type DunningStage =
  | 'upcoming'
  | 'due_today'
  | 'first_notice'
  | 'second_notice'
  | 'final_notice'
  | 'suspended'

export interface DunningNotice {
  id: string
  invoice_id: string
  invoice_number: string | null
  stage: DunningStage
  /** Where it went — email, in-app. `null` for a notice recorded before
   * channels were tracked. */
  channels: string | null
  sent_at: string
}

export interface CollectionsRunResult {
  marked_overdue: number
  notices_sent: number
  /** Company names, not counts: an operator about to explain a suspension
   * to somebody needs to know who, not how many. */
  suspended: string[]
  reinstated: string[]
}

export interface ExemptionInput {
  never_auto_suspend: boolean
  reason: string
}
