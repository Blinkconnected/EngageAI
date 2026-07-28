export interface CsatContext {
  conversation_id: string
  already_responded: boolean
  needs_contact_info: boolean
}

export interface CsatContactInfoRequest {
  email?: string
  phone?: string
}

// Deliberately does not echo the stored email/phone back — see the
// backend schema's docstring (api/schemas/csat.py).
export interface CsatContactInfoResponse {
  conversation_id: string
}

export interface CsatSubmitRequest {
  rating: number
  comment?: string
}

export interface CsatSubmitResponse {
  conversation_id: string
  rating: number
  comment: string | null
}
