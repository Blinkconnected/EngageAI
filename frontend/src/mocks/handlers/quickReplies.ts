import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { QuickReply } from '../../features/quickReplies/types'
import type { Page } from '../../shared/api/pagination'

/** Two live replies and one retired one.
 *
 * The retired one earns its place: the picker must never offer wording a
 * company has withdrawn, and a seed set of only active replies would let
 * that regression through unnoticed.
 */
export const MOCK_QUICK_REPLIES: QuickReply[] = [
  {
    id: 'qr-1',
    shortcut: '/refund',
    title: 'Refund policy',
    body: 'We refund any order within 30 days of delivery. Would you like me to start that for you?',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'qr-2',
    shortcut: '/hours',
    title: 'Opening hours',
    body: 'We are open Sunday to Thursday, 9am to 6pm.',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'qr-3',
    shortcut: '/oldpolicy',
    title: 'Withdrawn refund wording',
    body: 'We refund within 7 days.',
    is_active: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

export const quickRepliesHandlers = [
  http.get(`${API_BASE_URL}/quick-replies`, () =>
    HttpResponse.json<Page<QuickReply>>({
      items: MOCK_QUICK_REPLIES,
      total: MOCK_QUICK_REPLIES.length,
      page: 1,
      page_size: 100,
    }),
  ),
]
