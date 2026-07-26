import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { ErpConfig, ErpConfigCreateRequest, ErpSyncedRecord } from '../../features/erp/types'

let configs: ErpConfig[] = []
let nextConfigId = 100

const SEED_RECORDS: ErpSyncedRecord[] = [
  {
    id: 'rec-1',
    doctype: 'Sales Invoice',
    external_name: 'SINV-0001',
    data: { grand_total: 249.99, status: 'Paid', posting_date: '2026-01-15' },
    external_modified_at: '2026-01-15T00:00:00Z',
    synced_at: '2026-01-16T00:00:00Z',
  },
]

let records: ErpSyncedRecord[] = [...SEED_RECORDS]

export function resetErpMock() {
  configs = []
  nextConfigId = 100
  records = [...SEED_RECORDS]
}

export const erpHandlers = [
  http.get(`${API_BASE_URL}/erp-configs`, () =>
    HttpResponse.json({ items: configs, total: configs.length, page: 1, page_size: 1 }),
  ),

  http.post(`${API_BASE_URL}/erp-configs`, async ({ request }) => {
    const payload = (await request.json()) as ErpConfigCreateRequest
    const created: ErpConfig = {
      id: `erp-${nextConfigId}`,
      base_url: payload.base_url,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextConfigId += 1
    configs = [...configs, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.delete(`${API_BASE_URL}/erp-configs/:erpConfigId`, ({ params }) => {
    configs = configs.filter((config) => config.id !== params.erpConfigId)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE_URL}/erp-configs/test-connection`, () =>
    HttpResponse.json({ healthy: true, detail: null }),
  ),

  http.post(`${API_BASE_URL}/erp-configs/:erpConfigId/test-connection`, () =>
    HttpResponse.json({ healthy: true, detail: null }),
  ),

  http.get(`${API_BASE_URL}/customers/:customerId/erp-records`, () => HttpResponse.json(records)),

  http.post(`${API_BASE_URL}/customers/:customerId/erp-sync`, ({ params }) =>
    HttpResponse.json({
      customer_id: params.customerId,
      erp_customer_name: 'CUST-0001',
      synced_at: '2026-01-01T00:00:00Z',
    }),
  ),

  http.post(`${API_BASE_URL}/customers/:customerId/erp-pull/:doctype`, ({ params }) => {
    const pulled: ErpSyncedRecord = {
      id: 'rec-2',
      doctype: params.doctype as string,
      external_name: 'PULLED-0001',
      data: { pulled: true },
      external_modified_at: null,
      synced_at: '2026-01-01T00:00:00Z',
    }
    records = [...records, pulled]
    return HttpResponse.json(records)
  }),
]
