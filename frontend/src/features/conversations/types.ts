export type ConversationStatus = 'open' | 'pending' | 'resolved' | 'closed'

/** Matches the backend's `ConversationResponse`. */
export interface Conversation {
  id: string
  customer_id: string
  channel_config_id: string
  external_thread_id: string | null
  status: ConversationStatus
  queue_id: string | null
  assigned_agent_id: string | null
  department_id: string | null
  last_message_at: string | null
  first_response_at: string | null
  sla_first_response_breached_at: string | null
  sla_resolution_breached_at: string | null
  queue_entered_at: string | null
  picked_up_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export interface ConversationUpdateRequest {
  status?: ConversationStatus
  queue_id?: string | null
}

export type TransferTargetType = 'agent' | 'department' | 'queue'

export interface ConversationTransferRequest {
  target_type: TransferTargetType
  to_agent_id?: string | null
  to_department_id?: string | null
  note?: string | null
}

/** Matches the backend's `ConversationTransferResponse`. */
export interface ConversationTransfer {
  id: string
  conversation_id: string
  target_type: TransferTargetType
  from_agent_id: string | null
  to_agent_id: string | null
  to_department_id: string | null
  to_queue_id: string | null
  note: string | null
  transferred_by_user_id: string | null
  recipient_was_online: boolean
  created_at: string
}

export type MessageDirection = 'inbound' | 'outbound'
export type MessageType = 'text' | 'media' | 'system'
export type MessageStatus = 'pending' | 'sent' | 'failed'
export type DeliveryStatus = 'pending' | 'delivered' | 'undelivered' | 'not_applicable'
export type ReadStatus = 'unread' | 'read'

/** Matches the backend's `MessageResponse`. */
export interface Message {
  id: string
  conversation_id: string
  direction: MessageDirection
  message_type: MessageType
  status: MessageStatus
  delivery_status: DeliveryStatus
  read_status: ReadStatus
  body: string | null
  external_message_id: string | null
  reply_to_message_id: string | null
  message_metadata: Record<string, unknown>
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
  created_at: string
  attachments: Attachment[]
}

export interface SendMessageRequest {
  body?: string | null
  attachment_ids?: string[]
}

export type AttachmentValidationStatus = 'pending' | 'approved' | 'rejected'

/** Matches the backend's `AttachmentResponse`. */
export interface Attachment {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  validation_status: AttachmentValidationStatus
  message_id: string | null
  created_at: string
}

/** Matches the backend's `InternalNoteResponse`. */
export interface InternalNote {
  id: string
  conversation_id: string
  author_user_id: string | null
  body: string
  created_at: string
  updated_at: string
}

export const CONVERSATION_STATUSES: ConversationStatus[] = ['open', 'pending', 'resolved', 'closed']
