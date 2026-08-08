import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../shared/api/client'

export interface GuideResponse {
  language: 'en' | 'ar'
  /** True when the requested language was unavailable and English came back. */
  fell_back: boolean
  content: string
}

async function fetchGuide(lang: string): Promise<GuideResponse> {
  const { data } = await apiClient.get<GuideResponse>('/guide', { params: { lang } })
  return data
}

export function useGuideQuery() {
  const { i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'

  return useQuery({
    // Language is part of the key so switching refetches rather than
    // serving the previous language from cache.
    queryKey: ['guide', lang],
    queryFn: () => fetchGuide(lang),
    // The guide changes only across a deploy.
    staleTime: 30 * 60 * 1000,
  })
}
