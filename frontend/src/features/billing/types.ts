/** Mirrors the backend's billing schemas. See docs/architecture/billing.md. */

export type BillingInterval = 'month' | 'year'

export type SubscriptionStatus =
  | 'approval_pending'
  | 'active'
  | 'past_due'
  | 'suspended'
  | 'cancelled'
  | 'expired'

export type PaymentStatus = 'completed' | 'denied' | 'refunded'

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

export interface Subscription {
  id: string
  company_id: string
  plan_id: string
  plan_name: string
  amount: string
  currency: string
  interval: BillingInterval
  status: SubscriptionStatus
  /** Where the customer must go to approve the subscription in PayPal.
   * Kept so the page can re-offer the link if they closed the window
   * mid-checkout, rather than stranding a pending subscription. */
  approval_url: string | null
  current_period_end: string | null
  started_at: string | null
  cancelled_at: string | null
  failed_payment_count: number
}

export interface BillingPayment {
  id: string
  amount: string
  currency: string
  status: PaymentStatus
  occurred_at: string
}

export interface BillingOverview {
  /** False when this installation's operator has never connected PayPal.
   * The page then explains that instead of offering a Subscribe button
   * that can only fail. */
  is_configured: boolean
  subscription: Subscription | null
  plans: BillingPlan[]
  payments: BillingPayment[]
}
