import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import { MIN_SEARCH_QUERY_LENGTH, type SearchResults } from './types'

const SEARCH_KEY = (query: string) => ['search', query]

async function fetchSearchResults(query: string): Promise<SearchResults> {
  const { data } = await apiClient.get<SearchResults>('/search', { params: { q: query } })
  return data
}

/** Pass the *debounced* query — this fires on every value change. Stays
 * disabled below the shared minimum length (the backend enforces the
 * same floor, so a shorter query would return an empty result anyway).
 * `placeholderData` keeps the previous results on screen while the next
 * request is in flight, so the palette doesn't flash empty between
 * keystrokes. */
export function useSearchQuery(query: string) {
  const trimmed = query.trim()
  return useQuery({
    queryKey: SEARCH_KEY(trimmed),
    queryFn: () => fetchSearchResults(trimmed),
    enabled: trimmed.length >= MIN_SEARCH_QUERY_LENGTH,
    placeholderData: (previousData) => previousData,
    staleTime: 30_000,
  })
}
