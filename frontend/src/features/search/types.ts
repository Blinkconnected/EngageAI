/** Mirrors the backend's `SearchEntityType` literal union exactly. */
export type SearchEntityType =
  | 'conversation'
  | 'customer'
  | 'knowledge_article'
  | 'knowledge_category'
  | 'quick_reply'
  | 'agent'
  | 'team'
  | 'queue'
  | 'workflow'

/** Matches the backend's `SearchHitResponse`. */
export interface SearchHit {
  entity_type: SearchEntityType
  id: string
  title: string
  subtitle: string | null
}

/** Matches the backend's `SearchResponse`. */
export interface SearchResults {
  query: string
  results: SearchHit[]
  /** Which entity types the caller's own permissions actually allowed —
   * lets the UI say "we didn't search X" instead of implying "X had no
   * matches". */
  searched_entity_types: SearchEntityType[]
}

/** Where a result of each type navigates to, given its id.
 *
 * `null` means this entity type has no page to open yet — Knowledge
 * Base, Quick Replies, Teams and Workflows are fully built and
 * searchable on the backend but have no frontend route at all (see
 * `AppRoutes.tsx`). Their results are still shown, as non-navigable
 * rows, rather than hidden: "this exists, and here it is" is more
 * useful than silently pretending the match wasn't found. They become
 * navigable for free the moment those pages are built — only this map
 * changes.
 *
 * Queues and Agents have a list page but no per-entity detail route, so
 * they deep-link to the list itself. */
export const SEARCH_RESULT_PATHS: Record<SearchEntityType, ((id: string) => string) | null> = {
  conversation: (id) => `/conversations/${id}`,
  customer: (id) => `/customers/${id}`,
  agent: () => '/agents',
  queue: () => '/queues',
  knowledge_article: null,
  knowledge_category: null,
  quick_reply: null,
  team: null,
  workflow: null,
}

/** Render order for the grouped result list, and the i18n key suffix for
 * each type's group heading. Matches the backend's own `_SEARCHABLES`
 * order (most-frequently-jumped-to first). */
export const SEARCH_ENTITY_TYPE_ORDER: SearchEntityType[] = [
  'conversation',
  'customer',
  'agent',
  'knowledge_article',
  'knowledge_category',
  'quick_reply',
  'team',
  'queue',
  'workflow',
]

/** Server-side minimum too (`SearchService.MIN_QUERY_LENGTH`) — mirrored
 * here so the UI doesn't fire a request it knows will return nothing. */
export const MIN_SEARCH_QUERY_LENGTH = 2
