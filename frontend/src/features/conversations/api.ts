import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
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

export const CONVERSATIONS_LIST_KEY = ['conversations', 'list']
export const CONVERSATION_KEY = (id: string) => ['conversations', 'detail', id]
export const MESSAGES_KEY = (conversationId: string) => [
  'conversations',
  conversationId,
  'messages',
]
const NOTES_KEY = (conversationId: string) => ['conversations', conversationId, 'notes']
const TRANSFERS_KEY = (conversationId: string) => ['conversations', conversationId, 'transfers']

// A short, stable prefix (not the full per-conversation mutationKey below)
// so `queryClient.setMutationDefaults` — which matches by key *prefix* —
// applies to every conversation. Registered once in AppProviders.tsx so a
// reply queued while offline still has a real mutationFn to run once
// restored from storage after a reload, when the ReplyBox instance (and
// its closures) that originally called `.mutate()` no longer exists. See
// docs/architecture/frontend.md's "Offline support" section.
export const SEND_MESSAGE_MUTATION_KEY = ['conversations', 'send-message']

export interface ConversationListParams {
  status_filter?: ConversationStatus
  customer_id?: string
  assigned_agent_id?: string
  queue_id?: string
  unassigned_only?: boolean
}

async function fetchConversations(
  params: PageParams & ConversationListParams,
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

export interface SendMessageVariables {
  conversationId: string
  payload: SendMessageRequest
}

// Takes one combined, fully-serializable `variables` object rather than
// `(conversationId, payload)` — a restored-from-storage mutation (see
// registerOfflineMutationDefaults) has no closure to recover a
// conversationId from, only whatever was persisted as its variables.
async function sendMessage({ conversationId, payload }: SendMessageVariables): Promise<Message> {
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

async function pickConversation(conversationId: string): Promise<Conversation> {
  const { data } = await apiClient.post<Conversation>(`/conversations/${conversationId}/pick`)
  return data
}

async function releaseConversation(conversationId: string): Promise<Conversation> {
  const { data } = await apiClient.post<Conversation>(`/conversations/${conversationId}/release`)
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
  params: PageParams & ConversationListParams,
  options?: { refetchInterval?: number },
) {
  return useQuery({
    queryKey: [...CONVERSATIONS_LIST_KEY, params],
    queryFn: () => fetchConversations(params),
    placeholderData: (previousData) => previousData,
    // A more actively-watched surface (e.g. the Inbox's queue-filter mode —
    // see InboxPage.tsx) can pass a shorter interval than the Inbox's
    // default 30s; no shorter-than-30s precedent existed for a *list*
    // query elsewhere in this codebase (messages polls at 15s, but that's
    // a different query/surface — see useMessagesQuery below), so 10_000
    // was chosen for that caller rather than matched from prior art.
    refetchInterval: options?.refetchInterval ?? 30_000,
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
    // Suffixed with conversationId so React Query's own devtools/cache
    // still distinguish mutations per conversation — setMutationDefaults
    // below matches on this key's *prefix*, so it applies regardless.
    mutationKey: [...SEND_MESSAGE_MUTATION_KEY, conversationId],
    mutationFn: sendMessage,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY(conversationId) })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

/** Called once at app startup (see AppProviders.tsx) — not something a
 * component hook does on every render. Gives the mutation cache a real,
 * non-closure `mutationFn` to fall back on for a message-send mutation
 * restored from persisted storage after a reload (a live ReplyBox's own
 * `mutationFn`/`onSuccess` above always take precedence for anything
 * that happens in the same session — see useSendMessageMutation). */
export function registerOfflineMutationDefaults(queryClient: QueryClient) {
  queryClient.setMutationDefaults(SEND_MESSAGE_MUTATION_KEY, {
    mutationFn: sendMessage,
    onSuccess: (_message, variables) => {
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY(variables.conversationId) })
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

/** Claims a queued, unassigned conversation as the caller's own — see
 * InboxPage.tsx's "Pick" row action (`conversations.pick`). Same
 * invalidation shape as `useUpdateConversationMutation`: the mutated
 * conversation's own detail cache is written directly (no need to wait on
 * a refetch) and the list is invalidated so any "unassigned only" /
 * queue-filtered view stops showing it immediately. Takes the target
 * conversation's id as the mutate variable rather than a hook argument,
 * since a single Inbox render acts on whichever row was clicked, not one
 * conversation known up front. */
export function usePickConversationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (conversationId: string) => pickConversation(conversationId),
    onSuccess: (data, conversationId) => {
      queryClient.setQueryData(CONVERSATION_KEY(conversationId), data)
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

/** Releases a conversation back to its queue's shared pool, unassigning it
 * — see ConversationSidebar.tsx's "Release" button (`conversations.release`).
 * Same shape as `usePickConversationMutation` above. */
export function useReleaseConversationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (conversationId: string) => releaseConversation(conversationId),
    onSuccess: (data, conversationId) => {
      queryClient.setQueryData(CONVERSATION_KEY(conversationId), data)
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
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
