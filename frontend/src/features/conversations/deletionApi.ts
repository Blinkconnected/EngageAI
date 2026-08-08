import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import { CONVERSATIONS_LIST_KEY } from './api'

/** Matches the backend's `DeletionRequestStatus`. */
export type DeletionRequestStatus = 'pending' | 'approved' | 'rejected'

/** Matches the backend's `ConversationDeletionRequestResponse`. */
export interface ConversationDeletionRequest {
  id: string
  /** `null` once a hard purge has removed the conversation. The request
   * outlives it deliberately — the account of why something was deleted
   * is the part that matters once the thing itself is gone. */
  conversation_id: string | null
  customer_name: string | null
  status: DeletionRequestStatus
  reason: string
  requested_by_user_id: string | null
  requested_by_name: string | null
  decided_by_user_id: string | null
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string | null
  created_at: string
}

/** Server-side minimum too (`domain/conversation_deletion.py`) — mirrored
 * here so the form can say so before anybody submits. */
export const MIN_DELETION_REASON_LENGTH = 10

export const DELETION_REQUESTS_KEY = ['conversation-deletion-requests']
export const CONVERSATION_DELETION_KEY = (conversationId: string) => [
  'conversations',
  conversationId,
  'deletion-request',
]

async function fetchPending(conversationId: string): Promise<ConversationDeletionRequest | null> {
  const { data } = await apiClient.get<ConversationDeletionRequest | null>(
    `/conversations/${conversationId}/deletion-request`,
  )
  return data
}

/** Whether this conversation already has a request open against it.
 *
 * Read on every conversation so the interface can say "already asked"
 * instead of offering a button that will only ever 409.
 */
export function useConversationDeletionRequestQuery(conversationId: string | undefined) {
  return useQuery({
    queryKey: CONVERSATION_DELETION_KEY(conversationId ?? ''),
    queryFn: () => fetchPending(conversationId as string),
    enabled: Boolean(conversationId),
  })
}

export function useRequestConversationDeletionMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (reason: string) => {
      const { data } = await apiClient.post<ConversationDeletionRequest>(
        `/conversations/${conversationId}/deletion-request`,
        { reason },
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CONVERSATION_DELETION_KEY(conversationId) })
      void queryClient.invalidateQueries({ queryKey: DELETION_REQUESTS_KEY })
    },
  })
}

async function fetchRequests(
  params: PageParams & { status?: DeletionRequestStatus },
): Promise<Page<ConversationDeletionRequest>> {
  const { data } = await apiClient.get<Page<ConversationDeletionRequest>>(
    '/conversation-deletion-requests',
    { params },
  )
  return data
}

export function useDeletionRequestsQuery(
  params: PageParams & { status?: DeletionRequestStatus },
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: [...DELETION_REQUESTS_KEY, params],
    queryFn: () => fetchRequests(params),
    enabled: options?.enabled ?? true,
    placeholderData: (previous) => previous,
  })
}

/** Approving deletes the conversation, so the conversation list has to be
 * re-read as well as the queue — otherwise the row stays on screen and
 * opening it 404s. */
function useDecisionMutation(decision: 'approve' | 'reject') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ requestId, note }: { requestId: string; note?: string }) => {
      const { data } = await apiClient.post<ConversationDeletionRequest>(
        `/conversation-deletion-requests/${requestId}/${decision}`,
        { note: note ?? null },
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DELETION_REQUESTS_KEY })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

export function useApproveDeletionMutation() {
  return useDecisionMutation('approve')
}

export function useRejectDeletionMutation() {
  return useDecisionMutation('reject')
}
