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
  deployment_name: null,
  api_version: null,
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

/** Mirrors the real backend's `CompanyService._merge_settings`: a
 * top-level key present in the patch merges into that same key rather
 * than replacing it outright, and — one level deeper — if both sides
 * are object-shaped, THEIR keys are shallow-merged too (so patching
 * just `ai.autopilot` doesn't wipe out an already-saved `ai.enabled`,
 * the same "partial nested section" case the real backend handles). */
function mergeSettings(existing: CompanySettings, patch: CompanySettings): CompanySettings {
  const merged: Record<string, unknown> = { ...existing }
  for (const [key, value] of Object.entries(patch)) {
    const current = merged[key]
    if (
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      current !== null &&
      typeof current === 'object' &&
      !Array.isArray(current)
    ) {
      merged[key] = { ...current, ...value }
    } else {
      merged[key] = value
    }
  }
  return merged as CompanySettings
}

export const companyHandlers = [
  http.get(`${API_BASE_URL}/company`, () => HttpResponse.json(company)),

  http.patch(`${API_BASE_URL}/company`, async ({ request }) => {
    const body = (await request.json()) as { name?: string; settings?: CompanySettings }
    company = {
      ...company,
      name: body.name ?? company.name,
      settings: body.settings ? mergeSettings(company.settings, body.settings) : company.settings,
    }
    return HttpResponse.json(company)
  }),

  http.get(`${API_BASE_URL}/company/logo`, () => {
    const branding = company.settings.branding
    if (!branding?.logo_key || !branding.logo_content_type) {
      return HttpResponse.json({ detail: 'No logo has been uploaded' }, { status: 404 })
    }
    return new HttpResponse(new Blob(['fake-logo-bytes']), {
      headers: { 'Content-Type': branding.logo_content_type },
    })
  }),

  http.post(`${API_BASE_URL}/company/logo`, async ({ request }) => {
    const formData = await request.formData()
    const file = formData.get('file') as File | null
    company = {
      ...company,
      settings: {
        ...company.settings,
        branding: {
          logo_key: `logos/mock/${file?.name ?? 'logo'}`,
          logo_content_type: file?.type ?? 'image/png',
        },
      },
    }
    return HttpResponse.json(company)
  }),

  http.delete(`${API_BASE_URL}/company/logo`, () => {
    company = {
      ...company,
      settings: { ...company.settings, branding: { logo_key: null, logo_content_type: null } },
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
        deployment_name: body.deployment_name ?? null,
        api_version: body.api_version ?? null,
      }
    }
    return HttpResponse.json(aiConfig)
  }),
]
