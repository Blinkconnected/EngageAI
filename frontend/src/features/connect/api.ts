import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { ConnectCatalog, ConnectResult, WizardSession } from './types'

/**
 * The five calls the wizard makes.
 *
 * Deliberately thin: the server owns the flow, so there is no state machine
 * here to drift out of step with it. Every mutation returns the *whole*
 * session, and the console re-renders from that — which is why a refresh
 * mid-flow lands exactly where the customer left off instead of starting
 * over.
 */

const CATALOG_KEY = ['connect', 'catalog']
const sessionKey = (id: string) => ['connect', 'session', id]

async function fetchCatalog(): Promise<ConnectCatalog> {
  const { data } = await apiClient.get<ConnectCatalog>('/channel-connect/catalog')
  return data
}

/** What can be connected here, with each connector's manifest.
 *
 * Cached for the session: manifests are static by construction, and
 * re-fetching them on every wizard open would be asking the server to repeat
 * itself. */
export function useConnectCatalogQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: CATALOG_KEY,
    queryFn: fetchCatalog,
    staleTime: Infinity,
    enabled: options.enabled ?? true,
  })
}

export function useSessionQuery(sessionId: string | null) {
  return useQuery({
    queryKey: sessionKey(sessionId ?? ''),
    queryFn: async () => {
      const { data } = await apiClient.get<WizardSession>(`/channel-connect/sessions/${sessionId}`)
      return data
    },
    enabled: Boolean(sessionId),
  })
}

export function useStartSessionMutation() {
  return useMutation({
    mutationFn: async (input: { channelType?: string; templateKey?: string }) => {
      const { data } = await apiClient.post<WizardSession>('/channel-connect/sessions', {
        channel_type: input.channelType ?? null,
        template_key: input.templateKey ?? null,
      })
      return data
    },
  })
}

export function useAdvanceSessionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { sessionId: string; payload: Record<string, unknown> }) => {
      const { data } = await apiClient.post<WizardSession>(
        `/channel-connect/sessions/${input.sessionId}/advance`,
        { payload: input.payload },
      )
      return data
    },
    onSuccess: (session) => {
      // Seeded rather than invalidated: the response *is* the new state, so
      // re-fetching it would be a second round trip for something already in
      // hand — and on the discovery step that round trip costs the provider
      // several calls.
      queryClient.setQueryData(sessionKey(session.session_id), session)
    },
  })
}

export function useConnectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const { data } = await apiClient.post<ConnectResult>(
        `/channel-connect/sessions/${sessionId}/connect`,
      )
      return data
    },
    onSuccess: () => {
      // The channel list is now wrong in the one way that matters.
      void queryClient.invalidateQueries({ queryKey: ['channels', 'list'] })
    },
  })
}

export function useRepairMutation() {
  return useMutation({
    mutationFn: async (input: { channelConfigId: string; actionId: string }) => {
      const { data } = await apiClient.post<{
        action_id: string
        repaired: boolean
        reason: string | null
      }>(`/channel-connect/channels/${input.channelConfigId}/repair/${input.actionId}`)
      return data
    },
  })
}
