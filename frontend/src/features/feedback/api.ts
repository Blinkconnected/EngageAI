import { useMutation, useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  CsatContactInfoRequest,
  CsatContactInfoResponse,
  CsatContext,
  CsatSubmitRequest,
  CsatSubmitResponse,
} from './types'

async function fetchCsatContext(conversationId: string, token: string): Promise<CsatContext> {
  const { data } = await apiClient.get<CsatContext>(`/csat/${conversationId}`, {
    params: { token },
  })
  return data
}

async function submitContactInfo(
  conversationId: string,
  token: string,
  payload: CsatContactInfoRequest,
): Promise<CsatContactInfoResponse> {
  const { data } = await apiClient.post<CsatContactInfoResponse>(
    `/csat/${conversationId}/contact-info`,
    payload,
    { params: { token } },
  )
  return data
}

async function submitCsatResponse(
  conversationId: string,
  token: string,
  payload: CsatSubmitRequest,
): Promise<CsatSubmitResponse> {
  const { data } = await apiClient.post<CsatSubmitResponse>(
    `/csat/${conversationId}/respond`,
    payload,
    { params: { token } },
  )
  return data
}

/** No auth header is sent (the customer has no session — see
 * shared/api/client.ts) and no query invalidation is needed: this is a
 * one-shot, standalone public page, not part of the authenticated app's
 * cache graph. */
export function useCsatContextQuery(conversationId: string, token: string) {
  return useQuery({
    queryKey: ['csat-context', conversationId, token],
    queryFn: () => fetchCsatContext(conversationId, token),
    enabled: Boolean(conversationId) && Boolean(token),
    retry: false,
  })
}

export function useSubmitContactInfoMutation(conversationId: string, token: string) {
  return useMutation({
    mutationFn: (payload: CsatContactInfoRequest) =>
      submitContactInfo(conversationId, token, payload),
  })
}

export function useSubmitCsatResponseMutation(conversationId: string, token: string) {
  return useMutation({
    mutationFn: (payload: CsatSubmitRequest) => submitCsatResponse(conversationId, token, payload),
  })
}
