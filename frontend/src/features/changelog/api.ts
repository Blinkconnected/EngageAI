import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Release, VersionInfo } from './types'

async function fetchVersion(): Promise<VersionInfo> {
  const { data } = await apiClient.get<VersionInfo>('/version')
  return data
}

async function fetchReleases(): Promise<Release[]> {
  const { data } = await apiClient.get<Release[]>('/releases')
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
  return useQuery({
    queryKey: ['changelog', 'releases'],
    queryFn: fetchReleases,
    // Static release history parsed from CHANGELOG.md — effectively never
    // changes at runtime, same rationale as useVersionQuery above.
    staleTime: 5 * 60 * 1000,
  })
}
