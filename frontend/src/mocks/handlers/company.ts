import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Company, CompanySettings } from '../../features/company/types'

const SEED_COMPANY: Company = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Acme Corp',
  slug: 'acme-corp',
  status: 'active',
  settings: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

let company: Company = { ...SEED_COMPANY, settings: { ...SEED_COMPANY.settings } }

export function resetCompanyMock() {
  company = { ...SEED_COMPANY, settings: { ...SEED_COMPANY.settings } }
}

export const companyHandlers = [
  http.get(`${API_BASE_URL}/company`, () => HttpResponse.json(company)),

  http.patch(`${API_BASE_URL}/company`, async ({ request }) => {
    const body = (await request.json()) as { name?: string; settings?: CompanySettings }
    company = {
      ...company,
      name: body.name ?? company.name,
      // Shallow-merge per top-level key, mirroring CompanyService.update.
      settings: body.settings ? { ...company.settings, ...body.settings } : company.settings,
    }
    return HttpResponse.json(company)
  }),
]
