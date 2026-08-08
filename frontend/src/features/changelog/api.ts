import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../shared/api/client'
import type { Release, VersionInfo } from './types'

async function fetchVersion(): Promise<VersionInfo> {
  const { data } = await apiClient.get<VersionInfo>('/version')
  return data
}

async function fetchReleases(lang: string): Promise<Release[]> {
  const { data } = await apiClient.get<Release[]>('/releases', { params: { lang } })
  return data
}

export function useVersionQuery() {
  return useQuery({
    queryKey: ['changelog', 'version'],
    queryFn: fetchVersion,
    // The currently running release's identity only changes across a
    // deploy, never at runtime — unlike the live dashboard's
    // `refetchInterval`, a generous staleTime is all this needs.
    staleTime: 5 * 60 * 1000,
  })
}

export function useReleasesQuery() {
  const { i18n } = useTranslation()
  // Only 'en' and 'ar' exist server-side; anything else would 422, so a
  // language the interface gains before the changelog is translated
  // reads English rather than failing.
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'

  return useQuery({
    // Language is part of the key: switching language must refetch
    // rather than serve the previous language from cache.
    queryKey: ['changelog', 'releases', lang],
    queryFn: () => fetchReleases(lang),
    // Static release history parsed from CHANGELOG.md — effectively never
    // changes at runtime, same rationale as useVersionQuery above.
    staleTime: 5 * 60 * 1000,
  })
}
