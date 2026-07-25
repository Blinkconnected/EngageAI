import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { UserProfile } from '../../features/session/types'

export const MOCK_USER: UserProfile = {
  id: '11111111-1111-1111-1111-111111111111',
  email: 'owner@example.com',
  full_name: 'Ada Lovelace',
  is_company_owner: true,
  company: {
    id: '22222222-2222-2222-2222-222222222222',
    name: 'Acme Corp',
    slug: 'acme-corp',
  },
  roles: ['Owner'],
  permissions: [
    'company.manage',
    'agents.read',
    'agents.manage',
    'departments.read',
    'departments.manage',
    'channels.read',
    'channels.manage',
    'conversations.read',
    'conversations.manage',
    'conversations.delete',
    'conversations.transfer',
    'customers.read',
    'customers.manage',
    'erp.manage',
    'reports.read',
  ],
}

const MOCK_TOKENS = {
  access_token: 'mock-access-token',
  refresh_token: 'mock-refresh-token',
  token_type: 'bearer',
}

export const authHandlers = [
  http.post(`${API_BASE_URL}/auth/login`, () => HttpResponse.json(MOCK_TOKENS)),

  http.post(`${API_BASE_URL}/auth/register`, () =>
    HttpResponse.json({ user: MOCK_USER, tokens: MOCK_TOKENS }, { status: 201 }),
  ),

  http.post(`${API_BASE_URL}/auth/refresh`, () => HttpResponse.json(MOCK_TOKENS)),

  http.post(`${API_BASE_URL}/auth/logout`, () => new HttpResponse(null, { status: 204 })),

  http.get(`${API_BASE_URL}/auth/me`, () => HttpResponse.json(MOCK_USER)),

  http.post(`${API_BASE_URL}/auth/me/password`, () => new HttpResponse(null, { status: 204 })),
]
