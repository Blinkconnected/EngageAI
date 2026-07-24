/** Matches the backend's `ErpConfigResponse` — credentials and
 * webhook_secret are write-only, same contract as ChannelConfig. */
export interface ErpConfig {
  id: string
  base_url: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ErpConfigCreateRequest {
  base_url: string
  credentials: Record<string, unknown>
  webhook_secret?: string | null
}

export interface ErpConfigUpdateRequest {
  base_url?: string
  credentials?: Record<string, unknown>
  webhook_secret?: string | null
  is_active?: boolean
}

/** Matches the backend's `ErpSyncedRecordResponse` — doctype-agnostic by
 * design, `data` is the raw ERPNext document JSON with no fixed schema. */
export interface ErpSyncedRecord {
  id: string
  doctype: string
  external_name: string
  data: Record<string, unknown>
  external_modified_at: string | null
  synced_at: string
}

export interface ErpCustomerLink {
  customer_id: string
  erp_customer_name: string
  synced_at: string
}
