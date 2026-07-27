import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  AiConfig,
  AiConfigUpdateRequest,
  Company,
  CompanySettings,
} from '../../features/company/types'

const SEED_COMPANY: Company = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Acme Corp',
  slug: 'acme-corp',
  status: 'active',
  settings: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const SEED_AI_CONFIG: AiConfig = {
  provider: null,
  model: null,
  base_url: null,
  api_key_set: false,
}

let company: Company = { ...SEED_COMPANY, settings: { ...SEED_COMPANY.settings } }
let aiConfig: AiConfig = { ...SEED_AI_CONFIG }
// The mock's own stand-in for the backend's write-only encrypted column —
// never returned to a GET, only used to decide `api_key_set`.
let savedApiKey: string | null = null

export function resetCompanyMock() {
  company = { ...SEED_COMPANY, settings: { ...SEED_COMPANY.settings } }
  aiConfig = { ...SEED_AI_CONFIG }
  savedApiKey = null
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

  http.get(`${API_BASE_URL}/company/ai-config`, () => HttpResponse.json(aiConfig)),

  http.put(`${API_BASE_URL}/company/ai-config`, async ({ request }) => {
    const body = (await request.json()) as AiConfigUpdateRequest
    if (body.provider === null) {
      aiConfig = { ...SEED_AI_CONFIG }
      savedApiKey = null
    } else {
      if (body.api_key) savedApiKey = body.api_key
      aiConfig = {
        provider: body.provider,
        model: body.model ?? null,
        base_url: body.base_url ?? null,
        api_key_set: Boolean(savedApiKey),
      }
    }
    return HttpResponse.json(aiConfig)
  }),
]
