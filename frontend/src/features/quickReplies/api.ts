import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page } from '../../shared/api/pagination'
import type { QuickReply } from './types'

/** The whole set, once, filtered in the browser.
 *
 * Quick replies are a small, slow-moving list — tens per company, not
 * thousands — and the picker filters on every keystroke. Sending each
 * keystroke to the server's `search` param would put a request between
 * an agent and a phrase they are typing from muscle memory, which is
 * the one thing a shortcut must never do.
 */
const QUICK_REPLIES_ALL_KEY = ['quick-replies', 'all']

/** Above this, browser-side filtering stops being the right call and the
 * server's own `search` param should be used instead. Nothing enforces
 * it — it is the number at which to revisit the decision above. */
const FETCH_LIMIT = 100

async function fetchAllQuickReplies(): Promise<QuickReply[]> {
  const { data } = await apiClient.get<Page<QuickReply>>('/quick-replies', {
    params: { page: 1, page_size: FETCH_LIMIT },
  })
  // Inactive ones are retired phrasing kept for the record. Offering one
  // would put wording the company withdrew back in front of a customer.
  return data.items.filter((reply) => reply.is_active)
}

/**
 * @param enabled - `false` for an agent without `quick_replies.read`, so
 *   the picker never fires a request it knows will 403.
 */
export function useQuickRepliesQuery(enabled = true) {
  return useQuery({
    queryKey: QUICK_REPLIES_ALL_KEY,
    queryFn: fetchAllQuickReplies,
    enabled,
    // Saved replies change when somebody edits them in settings, which is
    // rarely, and re-fetching on every conversation switch would be a
    // request per click for a list that is almost always identical.
    staleTime: 5 * 60 * 1000,
  })
}
