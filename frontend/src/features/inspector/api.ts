import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { ConversationInspection } from './types'

async function fetchInspection(conversationId: string): Promise<ConversationInspection> {
  const { data } = await apiClient.get<ConversationInspection>(
    `/conversations/${conversationId}/inspector`,
  )
  return data
}

/** The whole story in one request.
 *
 * One call rather than six, matching the endpoint: somebody investigating
 * with a customer on the phone should not watch six spinners resolve in an
 * order that tells them nothing.
 *
 * Not polled. A conversation's history is what already happened, and a
 * screen that reloaded under a reader mid-investigation would move the thing
 * they were reading.
 */
export function useConversationInspection(conversationId: string, enabled = true) {
  return useQuery({
    queryKey: ['conversation-inspection', conversationId],
    queryFn: () => fetchInspection(conversationId),
    enabled: enabled && Boolean(conversationId),
    staleTime: 30_000,
  })
}
