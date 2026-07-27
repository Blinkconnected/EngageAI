import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { SearchEntityType, SearchHit, SearchResults } from '../../features/search/types'

/** One hit per entity type, so a test can assert both the navigable and
 * the not-yet-navigable branches (see `SEARCH_RESULT_PATHS`). Every
 * title contains "grace" so a single query exercises all of them. */
const SEED_HITS: SearchHit[] = [
  { entity_type: 'conversation', id: 'conv-1', title: 'Grace Blake', subtitle: 'open' },
  {
    entity_type: 'customer',
    id: 'cust-1',
    title: 'Grace Blake',
    subtitle: 'grace.blake@example.com',
  },
  { entity_type: 'agent', id: 'a1', title: 'Gracie Nolan', subtitle: 'Support Lead' },
  {
    entity_type: 'knowledge_article',
    id: 'kb-1',
    title: 'Grace period policy',
    subtitle: 'published',
  },
  { entity_type: 'quick_reply', id: 'qr-1', title: 'Grace period', subtitle: '/grace' },
  { entity_type: 'team', id: 'tm-1', title: 'Grace Team', subtitle: null },
  { entity_type: 'queue', id: 'q1', title: 'Grace Queue', subtitle: null },
  { entity_type: 'workflow', id: 'wf-1', title: 'Grace onboarding', subtitle: 'customer.created' },
]

const ALL_TYPES: SearchEntityType[] = [
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

export const searchHandlers = [
  http.get(`${API_BASE_URL}/search`, ({ request }) => {
    const query = (new URL(request.url).searchParams.get('q') ?? '').trim()
    // Mirrors SearchService's own server-side floor.
    if (query.length < 2) {
      const empty: SearchResults = { query, results: [], searched_entity_types: [] }
      return HttpResponse.json(empty)
    }
    const lowered = query.toLowerCase()
    const body: SearchResults = {
      query,
      results: SEED_HITS.filter((hit) => hit.title.toLowerCase().includes(lowered)),
      searched_entity_types: ALL_TYPES,
    }
    return HttpResponse.json(body)
  }),
]
