import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'

interface ReplySuggestionResponse {
  suggestion: string
}

interface ConversationSummaryResponse {
  summary: string
}

async function suggestReply(conversationId: string): Promise<string> {
  const { data } = await apiClient.post<ReplySuggestionResponse>(
    `/ai/conversations/${conversationId}/reply-suggestion`,
  )
  return data.suggestion
}

async function summarizeConversation(conversationId: string): Promise<string> {
  const { data } = await apiClient.post<ConversationSummaryResponse>(
    `/ai/conversations/${conversationId}/summary`,
  )
  return data.summary
}

/** Drafts a reply from the conversation history so far — the agent
 * reviews/edits it in the composer before sending, never auto-sent (see
 * docs/architecture/ai-engine.md's human-in-the-loop note). */
export function useSuggestReplyMutation() {
  return useMutation({ mutationFn: suggestReply })
}

/** Triggered on demand (not on mount) — every call is a real, metered LLM
 * request, same rationale as the reply-suggestion mutation above. */
export function useSummarizeConversationMutation() {
  return useMutation({ mutationFn: summarizeConversation })
}
