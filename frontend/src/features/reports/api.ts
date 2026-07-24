import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { apiClient } from '../../shared/api/client'
import type {
  AgentDashboard,
  AgentPerformanceRow,
  AiOperationRow,
  ConversationStatsRow,
  CsatReport,
  DateRange,
  ExecutiveDashboard,
  ExportFormat,
  QueueStatsRow,
  SlaReport,
} from './types'

async function fetchExecutiveDashboard(range: DateRange): Promise<ExecutiveDashboard> {
  const { data } = await apiClient.get<ExecutiveDashboard>('/reports/executive-dashboard', {
    params: range,
  })
  return data
}

export function useExecutiveDashboardQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'executive-dashboard', range],
    queryFn: () => fetchExecutiveDashboard(range),
  })
}

async function fetchAgentDashboard(range: DateRange): Promise<AgentDashboard> {
  const { data } = await apiClient.get<AgentDashboard>('/reports/agent-dashboard', {
    params: range,
  })
  return data
}

/** "My Performance" — the calling agent's own stats. 404s for a caller with
 * no Agent profile (e.g. an Owner/Admin who isn't also an agent); callers
 * should only mount this for users known to have an Agent role. */
export function useAgentDashboardQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'agent-dashboard', range],
    queryFn: () => fetchAgentDashboard(range),
    retry: false,
  })
}

async function fetchConversationsReport(range: DateRange): Promise<ConversationStatsRow[]> {
  const { data } = await apiClient.get<ConversationStatsRow[]>('/reports/conversations', {
    params: range,
  })
  return data
}

export function useConversationsReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'conversations', range],
    queryFn: () => fetchConversationsReport(range),
  })
}

async function fetchPerformanceReport(range: DateRange): Promise<AgentPerformanceRow[]> {
  const { data } = await apiClient.get<AgentPerformanceRow[]>('/reports/performance', {
    params: range,
  })
  return data
}

export function usePerformanceReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'performance', range],
    queryFn: () => fetchPerformanceReport(range),
  })
}

async function fetchQueuesReport(range: DateRange): Promise<QueueStatsRow[]> {
  const { data } = await apiClient.get<QueueStatsRow[]>('/reports/queues', { params: range })
  return data
}

export function useQueuesReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'queues', range],
    queryFn: () => fetchQueuesReport(range),
  })
}

async function fetchSlaReport(range: DateRange): Promise<SlaReport> {
  const { data } = await apiClient.get<SlaReport>('/reports/sla', { params: range })
  return data
}

export function useSlaReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'sla', range],
    queryFn: () => fetchSlaReport(range),
  })
}

async function fetchCsatReport(range: DateRange): Promise<CsatReport> {
  const { data } = await apiClient.get<CsatReport>('/reports/csat', { params: range })
  return data
}

export function useCsatReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'csat', range],
    queryFn: () => fetchCsatReport(range),
  })
}

async function fetchAiReport(range: DateRange): Promise<AiOperationRow[]> {
  const { data } = await apiClient.get<AiOperationRow[]>('/reports/ai', { params: range })
  return data
}

export function useAiReportQuery(range: DateRange) {
  return useQuery({
    queryKey: ['reports', 'ai', range],
    queryFn: () => fetchAiReport(range),
  })
}

const EXPORT_CONTENT_TYPE: Record<ExportFormat, string> = {
  pdf: 'application/pdf',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

async function downloadReportExport(
  path: string,
  range: DateRange,
  format: ExportFormat,
  fallbackFilename: string,
): Promise<void> {
  const response = await apiClient.get<Blob>(path, {
    params: { ...range, export: format },
    responseType: 'blob',
  })
  const disposition = response.headers['content-disposition'] as string | undefined
  const filename = disposition?.match(/filename="?([^"]+)"?/)?.[1] ?? fallbackFilename
  const blob = new Blob([response.data], { type: EXPORT_CONTENT_TYPE[format] })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/**
 * Every report list/detail endpoint (all except agent-dashboard and
 * live-dashboard) supports `?export=pdf|xlsx`, returning a binary file
 * instead of JSON — this triggers a real browser download rather than
 * navigating there directly, since the request needs the same
 * Authorization header as every other API call.
 */
export function useReportExport() {
  const [isExporting, setIsExporting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function exportReport(
    path: string,
    range: DateRange,
    format: ExportFormat,
    fallbackFilename: string,
  ) {
    setIsExporting(true)
    setError(null)
    try {
      await downloadReportExport(path, range, format, fallbackFilename)
    } catch (err) {
      setError(err)
    } finally {
      setIsExporting(false)
    }
  }

  return { exportReport, isExporting, error }
}
