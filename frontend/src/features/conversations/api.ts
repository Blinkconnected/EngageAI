import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  Attachment,
  Conversation,
  ConversationStatus,
  ConversationTransfer,
  ConversationTransferRequest,
  ConversationUpdateRequest,
  InternalNote,
  Message,
  SendMessageRequest,
} from './types'

const CONVERSATIONS_LIST_KEY = ['conversations', 'list']
const CONVERSATION_KEY = (id: string) => ['conversations', 'detail', id]
const MESSAGES_KEY = (conversationId: string) => ['conversations', conversationId, 'messages']
const NOTES_KEY = (conversationId: string) => ['conversations', conversationId, 'notes']
const TRANSFERS_KEY = (conversationId: string) => ['conversations', conversationId, 'transfers']

async function fetchConversations(
  params: PageParams & {
    status_filter?: ConversationStatus
    customer_id?: string
    assigned_agent_id?: string
  },
): Promise<Page<Conversation>> {
  const { data } = await apiClient.get<Page<Conversation>>('/conversations', { params })
  return data
}

async function fetchConversation(conversationId: string): Promise<Conversation> {
  const { data } = await apiClient.get<Conversation>(`/conversations/${conversationId}`)
  return data
}

async function updateConversation(
  conversationId: string,
  payload: ConversationUpdateRequest,
): Promise<Conversation> {
  const { data } = await apiClient.patch<Conversation>(`/conversations/${conversationId}`, payload)
  return data
}

async function fetchMessages(conversationId: string, params: PageParams): Promise<Page<Message>> {
  const { data } = await apiClient.get<Page<Message>>(`/conversations/${conversationId}/messages`, {
    params,
  })
  return data
}

async function sendMessage(conversationId: string, payload: SendMessageRequest): Promise<Message> {
  const { data } = await apiClient.post<Message>(
    `/conversations/${conversationId}/messages`,
    payload,
  )
  return data
}

async function uploadAttachment(conversationId: string, file: File): Promise<Attachment> {
  const formData = new FormData()
  formData.append('file', file)
  // `apiClient`'s instance default is `Content-Type: application/json` —
  // axios's transformRequest checks that *before* checking whether the
  // body is FormData, so left as-is it JSON-stringifies the FormData
  // instead of sending it as a real multipart body (the request never
  // even reaches the server as a file upload). Explicitly clearing it
  // per-request (not setting it to 'multipart/form-data', which would
  // omit the required boundary parameter and break parsing a different
  // way) lets axios/XHR generate the correct `multipart/form-data;
  // boundary=...` header itself from the FormData body.
  const { data } = await apiClient.post<Attachment>(
    `/conversations/${conversationId}/attachments`,
    formData,
    { headers: { 'Content-Type': undefined } },
  )
  return data
}

/**
 * The download endpoint needs the same Authorization header as every
 * other API call, so a plain `<img>`/`<a href>` can't hit it directly —
 * fetched as a blob instead, same pattern as the Reports PDF/Excel
 * export (`features/reports/api.ts`). Returns an object URL the caller
 * is responsible for revoking (`URL.revokeObjectURL`) once done with it.
 */
export async function fetchAttachmentBlobUrl(
  conversationId: string,
  attachmentId: string,
): Promise<string> {
  const response = await apiClient.get<Blob>(
    `/conversations/${conversationId}/attachments/${attachmentId}/download`,
    { responseType: 'blob' },
  )
  return URL.createObjectURL(response.data)
}

export async function downloadAttachment(
  conversationId: string,
  attachment: Attachment,
): Promise<void> {
  const url = await fetchAttachmentBlobUrl(conversationId, attachment.id)
  const link = document.createElement('a')
  link.href = url
  link.download = attachment.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function fetchNotes(conversationId: string, params: PageParams): Promise<Page<InternalNote>> {
  const { data } = await apiClient.get<Page<InternalNote>>(
    `/conversations/${conversationId}/notes`,
    { params },
  )
  return data
}

async function createNote(conversationId: string, body: string): Promise<InternalNote> {
  const { data } = await apiClient.post<InternalNote>(`/conversations/${conversationId}/notes`, {
    body,
  })
  return data
}

async function transferConversation(
  conversationId: string,
  payload: ConversationTransferRequest,
): Promise<ConversationTransfer> {
  const { data } = await apiClient.post<ConversationTransfer>(
    `/conversations/${conversationId}/transfer`,
    payload,
  )
  return data
}

async function fetchTransfers(
  conversationId: string,
  params: PageParams,
): Promise<Page<ConversationTransfer>> {
  const { data } = await apiClient.get<Page<ConversationTransfer>>(
    `/conversations/${conversationId}/transfers`,
    { params },
  )
  return data
}

export function useConversationsQuery(
  params: PageParams & {
    status_filter?: ConversationStatus
    customer_id?: string
    assigned_agent_id?: string
  },
) {
  return useQuery({
    queryKey: [...CONVERSATIONS_LIST_KEY, params],
    queryFn: () => fetchConversations(params),
    placeholderData: (previousData) => previousData,
    refetchInterval: 30_000,
  })
}

export function useConversationQuery(conversationId: string | undefined) {
  return useQuery({
    queryKey: CONVERSATION_KEY(conversationId ?? ''),
    queryFn: () => fetchConversation(conversationId as string),
    enabled: Boolean(conversationId),
  })
}

export function useUpdateConversationMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ConversationUpdateRequest) => updateConversation(conversationId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(CONVERSATION_KEY(conversationId), data)
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

export function useMessagesQuery(conversationId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...MESSAGES_KEY(conversationId ?? ''), params],
    queryFn: () => fetchMessages(conversationId as string, params),
    enabled: Boolean(conversationId),
    placeholderData: (previousData) => previousData,
    refetchInterval: 15_000,
  })
}

export function useSendMessageMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SendMessageRequest) => sendMessage(conversationId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY(conversationId) })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

export function useUploadAttachmentMutation(conversationId: string) {
  return useMutation({
    mutationFn: (file: File) => uploadAttachment(conversationId, file),
  })
}

export function useNotesQuery(conversationId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...NOTES_KEY(conversationId ?? ''), params],
    queryFn: () => fetchNotes(conversationId as string, params),
    enabled: Boolean(conversationId),
  })
}

export function useCreateNoteMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => createNote(conversationId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTES_KEY(conversationId) }),
  })
}

/** Reassigns a conversation to another agent or department — see
 * TransferDialog.tsx. Invalidates the conversation detail (assignment
 * changed), the company-wide list (an "Assigned to" column and any "My
 * conversations" filter both need to reflect it immediately — see
 * InboxPage.tsx), and this conversation's own transfer-history feed. */
export function useTransferConversationMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ConversationTransferRequest) =>
      transferConversation(conversationId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CONVERSATION_KEY(conversationId) })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
      void queryClient.invalidateQueries({ queryKey: TRANSFERS_KEY(conversationId) })
    },
  })
}

export function useTransfersQuery(conversationId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...TRANSFERS_KEY(conversationId ?? ''), params],
    queryFn: () => fetchTransfers(conversationId as string, params),
    enabled: Boolean(conversationId),
    placeholderData: (previousData) => previousData,
  })
}
