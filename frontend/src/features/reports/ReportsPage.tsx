import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Box, Tab, Tabs } from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { useCurrentUserQuery } from '../session/api'
import { DateRangeFilter } from './DateRangeFilter'
import { defaultDateRange } from './dateRange'
import { AiReportPanel } from './panels/AiReportPanel'
import { ConversationsReportPanel } from './panels/ConversationsReportPanel'
import { CsatReportPanel } from './panels/CsatReportPanel'
import { ExecutiveDashboardPanel } from './panels/ExecutiveDashboardPanel'
import { MyPerformancePanel } from './panels/MyPerformancePanel'
import { PerformanceReportPanel } from './panels/PerformanceReportPanel'
import { QueuesReportPanel } from './panels/QueuesReportPanel'
import { SlaReportPanel } from './panels/SlaReportPanel'

const TABS = [
  { value: 'executive', label: 'Executive', agentOnly: false },
  { value: 'conversations', label: 'Conversations', agentOnly: false },
  { value: 'performance', label: 'Agent Performance', agentOnly: false },
  { value: 'queues', label: 'Queues', agentOnly: false },
  { value: 'sla', label: 'SLA', agentOnly: false },
  { value: 'csat', label: 'CSAT', agentOnly: false },
  { value: 'ai', label: 'AI Usage', agentOnly: false },
  { value: 'my-performance', label: 'My Performance', agentOnly: true },
] as const

/**
 * A single date range (shared across every tab, defaulting to the last 30
 * days) drives all eight report endpoints — switching tabs keeps whatever
 * range is currently selected, matching how a supervisor actually compares
 * reports side by side. See docs/architecture/frontend.md's Reports section.
 */
export function ReportsPage() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()
  const { data: currentUser } = useCurrentUserQuery()
  const isAgent = currentUser?.roles.includes('Agent') ?? false

  const [range, setRange] = useState(defaultDateRange)

  const visibleTabs = TABS.filter((t) => !t.agentOnly || isAgent)
  const activeTab = visibleTabs.find((t) => t.value === tab)

  if (!activeTab) {
    return <Navigate to={`/reports/${visibleTabs[0].value}`} replace />
  }

  return (
    <>
      <PageHeader
        title="Reports"
        description="Executive, operational, and AI usage reporting across your company."
      />

      <DateRangeFilter range={range} onChange={setRange} />

      <Tabs
        value={activeTab.value}
        onChange={(_event, value: string) => navigate(`/reports/${value}`)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
      >
        {visibleTabs.map((t) => (
          <Tab key={t.value} value={t.value} label={t.label} id={`reports-tab-${t.value}`} />
        ))}
      </Tabs>

      <Box role="tabpanel" aria-labelledby={`reports-tab-${activeTab.value}`}>
        {activeTab.value === 'executive' && <ExecutiveDashboardPanel range={range} />}
        {activeTab.value === 'conversations' && <ConversationsReportPanel range={range} />}
        {activeTab.value === 'performance' && <PerformanceReportPanel range={range} />}
        {activeTab.value === 'queues' && <QueuesReportPanel range={range} />}
        {activeTab.value === 'sla' && <SlaReportPanel range={range} />}
        {activeTab.value === 'csat' && <CsatReportPanel range={range} />}
        {activeTab.value === 'ai' && <AiReportPanel range={range} />}
        {activeTab.value === 'my-performance' && <MyPerformancePanel range={range} />}
      </Box>
    </>
  )
}
