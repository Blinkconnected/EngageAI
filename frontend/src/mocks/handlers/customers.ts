import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  Customer,
  CustomerInternalRating,
  CustomerInternalRatingRequest,
  CustomerUpdateRequest,
} from '../../features/customers/types'

const SEED_CUSTOMER: Customer = {
  id: 'cust-1',
  full_name: 'Grace Blake',
  email: 'grace.blake@example.com',
  phone: null,
  notes: null,
  custom_fields: {},
  tags: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  rating_average: null,
  rating_count: 0,
}

export let MOCK_CUSTOMER: Customer = { ...SEED_CUSTOMER }
export let MOCK_CUSTOMER_RATINGS: CustomerInternalRating[] = []

export function resetCustomersMock() {
  MOCK_CUSTOMER = { ...SEED_CUSTOMER }
  MOCK_CUSTOMER_RATINGS = []
}

function recomputeRatingSummary() {
  const count = MOCK_CUSTOMER_RATINGS.length
  const average =
    count === 0
      ? null
      : Math.round((MOCK_CUSTOMER_RATINGS.reduce((sum, r) => sum + r.stars, 0) / count) * 100) / 100
  MOCK_CUSTOMER = { ...MOCK_CUSTOMER, rating_average: average, rating_count: count }
}

export const customersHandlers = [
  http.get(`${API_BASE_URL}/customers/:customerId`, ({ params }) =>
    HttpResponse.json({ ...MOCK_CUSTOMER, id: params.customerId as string }),
  ),

  http.get(`${API_BASE_URL}/customers`, () =>
    HttpResponse.json({ items: [MOCK_CUSTOMER], total: 1, page: 1, page_size: 20 }),
  ),

  http.patch(`${API_BASE_URL}/customers/:customerId`, async ({ request }) => {
    const payload = (await request.json()) as CustomerUpdateRequest
    MOCK_CUSTOMER = { ...MOCK_CUSTOMER, ...payload }
    return HttpResponse.json(MOCK_CUSTOMER)
  }),

  http.get(`${API_BASE_URL}/customers/:customerId/ratings`, () =>
    HttpResponse.json({
      items: MOCK_CUSTOMER_RATINGS,
      total: MOCK_CUSTOMER_RATINGS.length,
      page: 1,
      page_size: 50,
    }),
  ),

  http.post(`${API_BASE_URL}/customers/:customerId/ratings`, async ({ params, request }) => {
    const payload = (await request.json()) as CustomerInternalRatingRequest
    const rating: CustomerInternalRating = {
      id: `rating-${MOCK_CUSTOMER_RATINGS.length + 1}`,
      customer_id: params.customerId as string,
      rated_by_user_id: 'user-1',
      stars: payload.stars,
      note: payload.note ?? null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    MOCK_CUSTOMER_RATINGS = [rating, ...MOCK_CUSTOMER_RATINGS]
    recomputeRatingSummary()
    return HttpResponse.json(rating, { status: 201 })
  }),

  http.delete(`${API_BASE_URL}/customers/:customerId/ratings/:ratingId`, ({ params }) => {
    MOCK_CUSTOMER_RATINGS = MOCK_CUSTOMER_RATINGS.filter((r) => r.id !== params.ratingId)
    recomputeRatingSummary()
    return new HttpResponse(null, { status: 204 })
  }),
]
