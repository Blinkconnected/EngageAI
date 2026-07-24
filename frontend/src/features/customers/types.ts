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
