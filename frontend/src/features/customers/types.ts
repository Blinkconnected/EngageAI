/** Matches the backend's `CustomerResponse`. */
export interface Customer {
  id: string
  full_name: string
  email: string | null
  phone: string | null
  notes: string | null
  custom_fields: Record<string, unknown>
  tags: string[]
  created_at: string
  updated_at: string
  /** Internal staff rating summary — `null`/`0` if nobody has rated this
   * customer yet. Never shown to the customer themselves. */
  rating_average: number | null
  rating_count: number
}

/** Matches the backend's `CustomerInternalRatingResponse` — a single
 * staff-only star rating + optional note. Not customer-visible. */
export interface CustomerInternalRating {
  id: string
  customer_id: string
  rated_by_user_id: string | null
  stars: number
  note: string | null
  created_at: string
  updated_at: string
}

export interface CustomerInternalRatingRequest {
  stars: number
  note?: string | null
}

export interface CustomerCreateRequest {
  full_name: string
  email?: string | null
  phone?: string | null
  notes?: string | null
  custom_fields?: Record<string, unknown>
  tags?: string[]
}

export interface CustomerUpdateRequest {
  full_name?: string
  email?: string | null
  phone?: string | null
  notes?: string | null
  custom_fields?: Record<string, unknown>
  tags?: string[]
}
