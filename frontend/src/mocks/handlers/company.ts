import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Company } from '../../features/company/types'

export const MOCK_COMPANY: Company = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Acme Corp',
  slug: 'acme-corp',
  status: 'active',
  settings: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const companyHandlers = [
  http.get(`${API_BASE_URL}/company`, () => HttpResponse.json(MOCK_COMPANY)),

  http.patch(`${API_BASE_URL}/company`, async ({ request }) => {
    const body = (await request.json()) as { name?: string }
    return HttpResponse.json({ ...MOCK_COMPANY, name: body.name ?? MOCK_COMPANY.name })
  }),
]
