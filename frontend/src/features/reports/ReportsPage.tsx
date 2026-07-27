import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Alert, Box, Tab, Tabs } from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { useCurrentUserQuery } from '../session/api'
import { DateRangeFilter } from './DateRangeFilter'
import { defaultDateRange, isValidDateRange } from './dateRange'
import { AiReportPanel } from './panels/AiReportPanel'
import { ConversationsReportPanel } from './panels/ConversationsReportPanel'
import { CsatReportPanel } from './panels/CsatReportPanel'
import { ExecutiveDashboardPanel } from './panels/ExecutiveDashboardPanel'
import { MyPerformancePanel } from './panels/MyPerformancePanel'
import { PerformanceReportPanel } from './panels/PerformanceReportPanel'
import { QueuesReportPanel } from './panels/QueuesReportPanel'
import { SlaReportPanel } from './panels/SlaReportPanel'

const TABS = [
  { value: 'executive', labelKey: 'tabExecutive', agentOnly: false },
  { value: 'conversations', labelKey: 'tabConversations', agentOnly: false },
  { value: 'performance', labelKey: 'tabAgentPerformance', agentOnly: false },
  { value: 'queues', labelKey: 'tabQueues', agentOnly: false },
  { value: 'sla', labelKey: 'tabSla', agentOnly: false },
  { value: 'csat', labelKey: 'tabCsat', agentOnly: false },
  { value: 'ai', labelKey: 'tabAiUsage', agentOnly: false },
  { value: 'my-performance', labelKey: 'tabMyPerformance', agentOnly: true },
] as const

/**
 * A single date range (shared across every tab, defaulting to the last 30
 * days) drives all eight report endpoints — switching tabs keeps whatever
 * range is currently selected, matching how a supervisor actually compares
 * reports side by side. See docs/architecture/frontend.md's Reports section.
 */
export function ReportsPage() {
  const { t } = useTranslation('reportsCore')
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()
  const { data: currentUser } = useCurrentUserQuery()
  const isAgent = currentUser?.roles.includes('Agent') ?? false

  const [range, setRange] = useState(defaultDateRange)

  const visibleTabs = TABS.filter((tabDef) => !tabDef.agentOnly || isAgent)
  const activeTab = visibleTabs.find((tabDef) => tabDef.value === tab)

  if (!activeTab) {
    return <Navigate to={`/reports/${visibleTabs[0].value}`} replace />
  }

  return (
    <>
      <PageHeader title={t('ReportsPage.title')} description={t('ReportsPage.description')} />

      <DateRangeFilter range={range} onChange={setRange} />

      <Tabs
        value={activeTab.value}
        onChange={(_event, value: string) => navigate(`/reports/${value}`)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
      >
        {visibleTabs.map((tabDef) => (
          <Tab
            key={tabDef.value}
            value={tabDef.value}
            label={t(`ReportsPage.${tabDef.labelKey}`)}
            id={`reports-tab-${tabDef.value}`}
            aria-controls={`reports-tabpanel-${tabDef.value}`}
          />
        ))}
      </Tabs>

      <Box
        role="tabpanel"
        id={`reports-tabpanel-${activeTab.value}`}
        aria-labelledby={`reports-tab-${activeTab.value}`}
      >
        {!isValidDateRange(range) ? (
          <Alert severity="warning">{t('ReportsPage.invalidDateRangeWarning')}</Alert>
        ) : (
          <>
            {activeTab.value === 'executive' && <ExecutiveDashboardPanel range={range} />}
            {activeTab.value === 'conversations' && <ConversationsReportPanel range={range} />}
            {activeTab.value === 'performance' && <PerformanceReportPanel range={range} />}
            {activeTab.value === 'queues' && <QueuesReportPanel range={range} />}
            {activeTab.value === 'sla' && <SlaReportPanel range={range} />}
            {activeTab.value === 'csat' && <CsatReportPanel range={range} />}
            {activeTab.value === 'ai' && <AiReportPanel range={range} />}
            {activeTab.value === 'my-performance' && <MyPerformancePanel range={range} />}
          </>
        )}
      </Box>
    </>
  )
}
