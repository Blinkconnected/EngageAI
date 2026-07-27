export interface CsatContext {
  conversation_id: string
  already_responded: boolean
  needs_contact_info: boolean
}

export interface CsatContactInfoRequest {
  email?: string
  phone?: string
}

export interface CsatContactInfoResponse {
  conversation_id: string
  email: string | null
  phone: string | null
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
