import { Box, Stack, Tab, Tabs } from '@mui/material'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { ErpConnectionPanel } from '../erp/ErpConnectionPanel'
import { useCompanyQuery } from './api'
import { AiSettingsPanel } from './panels/AiSettingsPanel'
import { BrandingSettingsPanel } from './panels/BrandingSettingsPanel'
import { BusinessHoursSettingsPanel } from './panels/BusinessHoursSettingsPanel'
import { ErpEnableToggle } from './panels/ErpEnableToggle'
import { GeneralSettingsPanel } from './panels/GeneralSettingsPanel'
import { LanguageSettingsPanel } from './panels/LanguageSettingsPanel'
import { MessagingSettingsPanel } from './panels/MessagingSettingsPanel'
import { NotificationsSettingsPanel } from './panels/NotificationsSettingsPanel'
import { SecuritySettingsPanel } from './panels/SecuritySettingsPanel'
import { TimezoneSettingsPanel } from './panels/TimezoneSettingsPanel'
import type { Company } from './types'

const BASE_TABS = [
  { value: 'general', label: 'General' },
  { value: 'branding', label: 'Branding' },
  { value: 'language', label: 'Language' },
  { value: 'timezone', label: 'Timezone' },
  { value: 'business-hours', label: 'Business Hours' },
  { value: 'notifications', label: 'Notifications' },
  { value: 'messaging', label: 'Messaging' },
  { value: 'security', label: 'Security' },
  { value: 'ai', label: 'AI' },
] as const

const ERP_TAB = { value: 'erp', label: 'ERP' } as const

function visibleTabsFor(company: Company) {
  return company.settings.erp?.enabled ? [...BASE_TABS, ERP_TAB] : BASE_TABS
}

export function CompanySettingsPage() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()
  const companyQuery = useCompanyQuery()

  return (
    <>
      <PageHeader title="Settings" description="Manage your company's profile." />

      {companyQuery.isPending && <LoadingState label="Loading settings…" />}
      {companyQuery.isError && (
        <ErrorState error={companyQuery.error} onRetry={() => companyQuery.refetch()} />
      )}

      {companyQuery.data && (
        <CompanySettingsTabs company={companyQuery.data} tab={tab} navigate={navigate} />
      )}
    </>
  )
}

function CompanySettingsTabs({
  company,
  tab,
  navigate,
}: {
  company: Company
  tab: string | undefined
  navigate: (path: string) => void
}) {
  const visibleTabs = visibleTabsFor(company)
  const activeTab = visibleTabs.find((t) => t.value === tab)

  if (!activeTab) {
    return <Navigate to={`/settings/company/${visibleTabs[0].value}`} replace />
  }

  return (
    <>
      <Tabs
        value={activeTab.value}
        onChange={(_event, value: string) => navigate(`/settings/company/${value}`)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
      >
        {visibleTabs.map((t) => (
          <Tab key={t.value} value={t.value} label={t.label} id={`company-settings-tab-${t.value}`} />
        ))}
      </Tabs>

      <Box role="tabpanel" aria-labelledby={`company-settings-tab-${activeTab.value}`}>
        {activeTab.value === 'general' && (
          <Stack spacing={2}>
            <GeneralSettingsPanel company={company} />
            <ErpEnableToggle company={company} />
          </Stack>
        )}
        {activeTab.value === 'branding' && <BrandingSettingsPanel company={company} />}
        {activeTab.value === 'language' && <LanguageSettingsPanel company={company} />}
        {activeTab.value === 'timezone' && <TimezoneSettingsPanel company={company} />}
        {activeTab.value === 'business-hours' && <BusinessHoursSettingsPanel company={company} />}
        {activeTab.value === 'notifications' && <NotificationsSettingsPanel company={company} />}
        {activeTab.value === 'messaging' && <MessagingSettingsPanel company={company} />}
        {activeTab.value === 'security' && <SecuritySettingsPanel company={company} />}
        {activeTab.value === 'ai' && <AiSettingsPanel company={company} />}
        {activeTab.value === 'erp' && <ErpConnectionPanel />}
      </Box>
    </>
  )
}
