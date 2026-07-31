import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  AgingReport,
  AllocatePaymentInput,
  AllocationPage,
  CollectionsRunResult,
  CompanyStanding,
  CreditableLines,
  CreditNoteLineSelection,
  CreditNotePreview,
  DunningNotice,
  ExemptionInput,
  Invoice,
  InvoiceDetail,
  InvoiceSearchParams,
  InvoiceSearchResult,
  IssueCreditNoteInput,
  LedgerAccount,
  LedgerStatement,
  Payment,
  RecordPaymentInput,
  Refund,
  RefundableAmount,
  RevenueOverview,
  TrialBalance,
} from './types'

/**
 * Everything the Billing Console reads and writes.
 *
 * One convention runs through the file: **after any write, invalidate
 * broadly.** A payment moves an invoice's status, the company's standing, the
 * aging report, the ledger and the revenue figures at once, and a console
 * showing five panels where one has caught up is worse than one that briefly
 * shows spinners. Finance work is deliberate — a refetch costs a moment, a
 * stale receivable costs a phone call to a customer who already paid.
 */

const BILLING_OPS_KEY = ['billing-ops']
const REVENUE_KEY = [...BILLING_OPS_KEY, 'revenue']
const INVOICES_KEY = [...BILLING_OPS_KEY, 'invoices']
const PAYMENTS_KEY = [...BILLING_OPS_KEY, 'payments']
const LEDGER_KEY = [...BILLING_OPS_KEY, 'ledger']
const COLLECTIONS_KEY = [...BILLING_OPS_KEY, 'collections']

/** Everything money touches. Used after every write. */
function useInvalidateBilling() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: BILLING_OPS_KEY })
}

// --- Revenue ---------------------------------------------------------

export interface RevenueWindow {
  since?: string
  until?: string
}

export function useRevenueQuery(window: RevenueWindow = {}) {
  return useQuery({
    queryKey: [...REVENUE_KEY, window],
    queryFn: async (): Promise<RevenueOverview> => {
      const { data } = await apiClient.get<RevenueOverview>('/platform/billing/revenue', {
        params: window,
      })
      return data
    },
  })
}

// --- Invoices --------------------------------------------------------

export function useInvoiceSearchQuery(params: InvoiceSearchParams) {
  return useQuery({
    queryKey: [...INVOICES_KEY, 'search', params],
    queryFn: async (): Promise<InvoiceSearchResult> => {
      const { data } = await apiClient.get<InvoiceSearchResult>(
        '/platform/invoices/search',
        { params },
      )
      return data
    },
  })
}

export function useInvoiceQuery(invoiceId: string | null) {
  return useQuery({
    queryKey: [...INVOICES_KEY, invoiceId],
    enabled: Boolean(invoiceId),
    queryFn: async (): Promise<InvoiceDetail> => {
      const { data } = await apiClient.get<InvoiceDetail>(
        `/platform/invoices/${invoiceId}`,
      )
      return data
    },
  })
}

/**
 * Downloads the current search as CSV.
 *
 * Deliberately not a plain `<a href>`: the export carries the same bearer
 * token as every other call, and a link would send the browser off without
 * it. The blob is revoked immediately after the click — a leaked object URL
 * pins the whole file in memory for the life of the tab.
 */
export async function downloadInvoiceCsv(params: InvoiceSearchParams): Promise<void> {
  const response = await apiClient.get('/platform/invoices/search', {
    params: { ...params, export: 'csv' },
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = disposition.match(/filename="?([^";]+)"?/)
  const url = URL.createObjectURL(response.data as Blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? 'invoices.csv'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * Downloads an invoice as PDF, or opens it for printing.
 *
 * Fetched through the authenticated client rather than linked to directly: an
 * `<a href>` sends the browser off without the bearer token, and the response
 * would be a 403 rendered as a broken download.
 *
 * `open` puts the blob in a new tab, where the browser's own viewer gives the
 * operator print, zoom and save for free — building a preview pane here would
 * be a worse version of something every browser already has.
 */
export async function fetchInvoicePdf(
  invoiceId: string,
  { open = false }: { open?: boolean } = {},
): Promise<void> {
  const response = await apiClient.get(`/platform/invoices/${invoiceId}/pdf`, {
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = disposition.match(/filename="?([^";]+)"?/)
  const url = URL.createObjectURL(response.data as Blob)
  if (open) {
    window.open(url, '_blank', 'noopener')
    // Not revoked immediately: the new tab is still loading from this URL,
    // and revoking it out from under the viewer shows a blank page. The
    // browser releases it when the tab closes.
    return
  }
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? `invoice-${invoiceId}.pdf`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function useEmailInvoiceMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (invoiceId: string): Promise<{ sent_to: string[] }> => {
      const { data } = await apiClient.post<{ sent_to: string[] }>(
        `/platform/invoices/${invoiceId}/email`,
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useIssueInvoiceMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (invoiceId: string): Promise<InvoiceDetail> => {
      const { data } = await apiClient.post<InvoiceDetail>(
        `/platform/invoices/${invoiceId}/issue`,
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useCancelInvoiceMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { invoiceId: string; reason: string }): Promise<Invoice> => {
      const { data } = await apiClient.post<Invoice>(
        `/platform/invoices/${input.invoiceId}/cancel`,
        { reason: input.reason },
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useCreditableLinesQuery(invoiceId: string | null) {
  return useQuery({
    queryKey: [...INVOICES_KEY, invoiceId, 'creditable'],
    enabled: Boolean(invoiceId),
    queryFn: async (): Promise<CreditableLines> => {
      const { data } = await apiClient.get<CreditableLines>(
        `/platform/invoices/${invoiceId}/creditable`,
      )
      return data
    },
  })
}

/**
 * What the credit note would say, worked out by the server.
 *
 * A query rather than a mutation despite being a POST — it writes nothing,
 * and the selection is a list, which does not belong in a query string. It
 * runs the write path's own validation, so a total shown here is the total
 * the document will carry and a selection accepted here cannot be refused a
 * moment later by the save.
 *
 * The console never multiplies a quantity by a price itself. That is the same
 * rule the rest of this feature follows, and it is what makes the previewed
 * figure the *actual* figure rather than a good guess at it.
 */
export function useCreditNotePreviewQuery(
  invoiceId: string | null,
  selections: CreditNoteLineSelection[],
) {
  return useQuery({
    queryKey: [...INVOICES_KEY, invoiceId, 'credit-preview', selections],
    enabled: Boolean(invoiceId) && selections.length > 0,
    // A refused selection is an answer, not a transient failure: retrying a
    // quantity the server has already rejected just delays telling the
    // operator why.
    retry: false,
    queryFn: async (): Promise<CreditNotePreview> => {
      const { data } = await apiClient.post<CreditNotePreview>(
        `/platform/invoices/${invoiceId}/credit-notes/preview`,
        { lines: selections },
      )
      return data
    },
  })
}

export function useCreditNoteMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { invoiceId: string; body: IssueCreditNoteInput }) => {
      const { data } = await apiClient.post(
        `/platform/invoices/${input.invoiceId}/credit-notes`,
        input.body,
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useWriteOffMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { invoiceId: string; reason: string }) => {
      const { data } = await apiClient.post(
        `/platform/ledger/write-offs/${input.invoiceId}`,
        { reason: input.reason },
      )
      return data
    },
    onSuccess: invalidate,
  })
}

// --- Payments --------------------------------------------------------

export function useCompanyPaymentsQuery(companyId: string | null) {
  return useQuery({
    queryKey: [...PAYMENTS_KEY, 'company', companyId],
    enabled: Boolean(companyId),
    queryFn: async (): Promise<Payment[]> => {
      const { data } = await apiClient.get<Payment[]>(
        `/platform/invoices/payments/company/${companyId}`,
      )
      return data
    },
  })
}

export interface AllocationParams {
  company_id?: string
  payment_id?: string
  invoice_id?: string
  limit?: number
  offset?: number
}

export function useAllocationsQuery(params: AllocationParams) {
  return useQuery({
    queryKey: [...PAYMENTS_KEY, 'allocations', params],
    queryFn: async (): Promise<AllocationPage> => {
      const { data } = await apiClient.get<AllocationPage>('/platform/payments/allocations', {
        params,
      })
      return data
    },
  })
}

export function useRecordPaymentMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: RecordPaymentInput): Promise<Payment> => {
      const { data } = await apiClient.post<Payment>('/platform/invoices/payments', input)
      return data
    },
    onSuccess: invalidate,
  })
}

export function useAllocatePaymentMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { paymentId: string; body: AllocatePaymentInput }) => {
      const { data } = await apiClient.post(
        `/platform/invoices/payments/${input.paymentId}/allocate`,
        input.body,
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useReverseAllocationMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { allocationId: string; reason: string }) => {
      const { data } = await apiClient.post(
        `/platform/payments/allocations/${input.allocationId}/reverse`,
        { reason: input.reason },
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useRefundableQuery(paymentId: string | null) {
  return useQuery({
    queryKey: [...PAYMENTS_KEY, paymentId, 'refundable'],
    enabled: Boolean(paymentId),
    queryFn: async (): Promise<RefundableAmount> => {
      const { data } = await apiClient.get<RefundableAmount>(
        `/platform/payments/${paymentId}/refundable`,
      )
      return data
    },
  })
}

export function useRefundsQuery(paymentId: string | null) {
  return useQuery({
    queryKey: [...PAYMENTS_KEY, paymentId, 'refunds'],
    enabled: Boolean(paymentId),
    queryFn: async (): Promise<Refund[]> => {
      const { data } = await apiClient.get<Refund[]>(
        `/platform/payments/${paymentId}/refunds`,
      )
      return data
    },
  })
}

export function useRefundMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { paymentId: string; amount: string; reason: string }) => {
      const { data } = await apiClient.post<Refund>(
        `/platform/payments/${input.paymentId}/refund`,
        { amount: input.amount, reason: input.reason },
      )
      return data
    },
    onSuccess: invalidate,
  })
}

// --- Ledger ----------------------------------------------------------

export interface StatementParams {
  account?: LedgerAccount
  currency?: string
  since?: string
  until?: string
  limit?: number
  offset?: number
}

export function useLedgerStatementQuery(companyId: string | null, params: StatementParams) {
  return useQuery({
    queryKey: [...LEDGER_KEY, 'statement', companyId, params],
    enabled: Boolean(companyId),
    queryFn: async (): Promise<LedgerStatement> => {
      const { data } = await apiClient.get<LedgerStatement>(
        `/platform/ledger/statement/${companyId}`,
        { params },
      )
      return data
    },
  })
}

export function useTrialBalanceQuery() {
  return useQuery({
    queryKey: [...LEDGER_KEY, 'trial-balance'],
    queryFn: async (): Promise<TrialBalance[]> => {
      const { data } = await apiClient.get<TrialBalance[]>('/platform/ledger/trial-balance')
      return data
    },
  })
}

// --- Collections -----------------------------------------------------

export function useAgingQuery(companyId?: string) {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY, 'aging', companyId ?? 'all'],
    queryFn: async (): Promise<AgingReport> => {
      const { data } = await apiClient.get<AgingReport>(
        '/platform/payments/collections/aging',
        { params: companyId ? { company_id: companyId } : undefined },
      )
      return data
    },
  })
}

export function useCollectionsStatusQuery() {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY, 'status'],
    queryFn: async (): Promise<CompanyStanding[]> => {
      const { data } = await apiClient.get<CompanyStanding[]>(
        '/platform/payments/collections/status',
      )
      return data
    },
  })
}

export function useCompanyStandingQuery(companyId: string | null) {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY, 'standing', companyId],
    enabled: Boolean(companyId),
    queryFn: async (): Promise<CompanyStanding> => {
      const { data } = await apiClient.get<CompanyStanding>(
        `/platform/billing/companies/${companyId}/standing`,
      )
      return data
    },
  })
}

export function useNoticesQuery(invoiceId: string | null) {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY, 'notices', invoiceId],
    enabled: Boolean(invoiceId),
    queryFn: async (): Promise<DunningNotice[]> => {
      const { data } = await apiClient.get<DunningNotice[]>(
        `/platform/payments/collections/notices/${invoiceId}`,
      )
      return data
    },
  })
}

export function useRunCollectionsMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (): Promise<CollectionsRunResult> => {
      const { data } = await apiClient.post<CollectionsRunResult>(
        '/platform/payments/collections/run',
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useReinstateMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (companyId: string) => {
      const { data } = await apiClient.post(
        `/platform/payments/collections/${companyId}/reinstate`,
      )
      return data
    },
    onSuccess: invalidate,
  })
}

export function useExemptionMutation() {
  const invalidate = useInvalidateBilling()
  return useMutation({
    mutationFn: async (input: { companyId: string; body: ExemptionInput }) => {
      const { data } = await apiClient.put(
        `/platform/payments/collections/${input.companyId}/exemption`,
        input.body,
      )
      return data
    },
    onSuccess: invalidate,
  })
}
