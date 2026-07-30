export type ConversationStatus = 'open' | 'pending' | 'resolved' | 'closed'

/** A triage signal, independent of SLA policy targets — drives the
 * Inbox's default sort order and visual urgency only. Ordered low to
 * high so `CONVERSATION_PRIORITIES.indexOf(p)` is a comparable rank. */
export type ConversationPriority = 'low' | 'normal' | 'high' | 'urgent'

/** Matches the backend's `ConversationResponse`. */
export interface Conversation {
  id: string
  customer_id: string
  channel_config_id: string
  external_thread_id: string | null
  status: ConversationStatus
  priority: ConversationPriority
  queue_id: string | null
  assigned_agent_id: string | null
  department_id: string | null
  last_message_at: string | null
  first_response_at: string | null
  sla_first_response_breached_at: string | null
  sla_resolution_breached_at: string | null
  /** Set once a conversation crosses its SLA policy's warning threshold
   * (e.g. 80% of the target), *before* it actually breaches — lets the
   * Inbox show "approaching SLA" as an earlier, distinct state from
   * "breached." */
  sla_first_response_warned_at: string | null
  sla_resolution_warned_at: string | null
  queue_entered_at: string | null
  picked_up_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
  /** AI Autopilot — true while the AI, not a human, is responsible for
   * replying to this conversation. */
  autopilot_active: boolean
  /** Unread INBOUND message count — clears the instant an agent opens
   * the conversation (GET .../messages marks them read server-side). */
  unread_count: number
}

export interface ConversationUpdateRequest {
  status?: ConversationStatus
  priority?: ConversationPriority
  queue_id?: string | null
}

export const CONVERSATION_PRIORITIES: ConversationPriority[] = ['low', 'normal', 'high', 'urgent']

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
  /** The draft started as an AI suggestion (edited or not). Distinct
   * from a message's `is_ai_generated` metadata, which marks a reply AI
   * Autopilot sent unattended — this one is a human's own reply that AI
   * helped write, which reporting counts separately. */
  is_ai_assisted?: boolean
}

export type AttachmentValidationStatus = 'pending' | 'approved' | 'rejected'

/** Matches the backend's `AttachmentResponse`. */
/** What an attachment is, for presentation. Decided server-side from the
 * content type — the console deliberately carries no MIME table of its
 * own, because a second one drifts from the one the upload path validates
 * against. */
export type MediaKind = 'image' | 'video' | 'audio' | 'document' | 'file'

export interface Attachment {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  validation_status: AttachmentValidationStatus
  message_id: string | null
  created_at: string
  kind: MediaKind
  /** Whether the browser can show it in the conversation itself. */
  inline: boolean
  /** An image the browser may refuse to decode — HEIC from an iPhone,
   * TIFF. Offer "open in a new tab" prominently rather than rendering a
   * broken image and leaving an agent thinking the file is corrupt. */
  needs_fallback: boolean
  /** Known for images. Used to reserve the right space *before* loading,
   * so a thread of photos does not reflow as each arrives. */
  width: number | null
  height: number | null
  /** A short-lived URL usable directly in `<img>`/`<video>`. Null for
   * anything not renderable inline. */
  media_url: string | null
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
