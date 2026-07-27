import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { AiConfig, AiConfigUpdateRequest } from './types'

const AI_CONFIG_QUERY_KEY = ['company', 'ai-config']

async function fetchAiConfig(): Promise<AiConfig> {
  const { data } = await apiClient.get<AiConfig>('/company/ai-config')
  return data
}

async function updateAiConfig(payload: AiConfigUpdateRequest): Promise<AiConfig> {
  const { data } = await apiClient.put<AiConfig>('/company/ai-config', payload)
  return data
}

export function useAiConfigQuery() {
  return useQuery({ queryKey: AI_CONFIG_QUERY_KEY, queryFn: fetchAiConfig })
}

export function useUpdateAiConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateAiConfig,
    onSuccess: (data) => {
      queryClient.setQueryData(AI_CONFIG_QUERY_KEY, data)
    },
  })
}
