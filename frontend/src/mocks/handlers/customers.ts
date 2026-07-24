import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Customer } from '../../features/customers/types'

export const MOCK_CUSTOMER: Customer = {
  id: 'cust-1',
  full_name: 'Grace Blake',
  email: 'grace.blake@example.com',
  phone: null,
  notes: null,
  custom_fields: {},
  tags: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const customersHandlers = [
  http.get(`${API_BASE_URL}/customers/:customerId`, ({ params }) =>
    HttpResponse.json({ ...MOCK_CUSTOMER, id: params.customerId as string }),
  ),

  http.get(`${API_BASE_URL}/customers`, () =>
    HttpResponse.json({ items: [MOCK_CUSTOMER], total: 1, page: 1, page_size: 20 }),
  ),
]
