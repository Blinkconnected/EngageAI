import { Box, Stack, Tab, Tabs } from '@mui/material'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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

function baseTabsFor(t: (key: string) => string) {
  return [
    { value: 'general', label: t('CompanySettingsPage.tabGeneral') },
    { value: 'language', label: t('CompanySettingsPage.tabLanguage') },
    { value: 'timezone', label: t('CompanySettingsPage.tabTimezone') },
    { value: 'business-hours', label: t('CompanySettingsPage.tabBusinessHours') },
    { value: 'notifications', label: t('CompanySettingsPage.tabNotifications') },
    { value: 'messaging', label: t('CompanySettingsPage.tabMessaging') },
    { value: 'security', label: t('CompanySettingsPage.tabSecurity') },
    { value: 'ai', label: t('CompanySettingsPage.tabAi') },
    // Branding lives at the bottom of Settings — it's the tab an owner
    // touches least often (set once at onboarding, rarely revisited),
    // unlike General/Language/Security above it.
    { value: 'branding', label: t('CompanySettingsPage.tabBranding') },
  ] as const
}

function erpTabFor(t: (key: string) => string) {
  return { value: 'erp', label: t('CompanySettingsPage.tabErp') } as const
}

function visibleTabsFor(company: Company, t: (key: string) => string) {
  const baseTabs = baseTabsFor(t)
  return company.settings.erp?.enabled ? [...baseTabs, erpTabFor(t)] : baseTabs
}

export function CompanySettingsPage() {
  const { t } = useTranslation('companySettings')
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()
  const companyQuery = useCompanyQuery()

  return (
    <>
      <PageHeader
        title={t('CompanySettingsPage.title')}
        description={t('CompanySettingsPage.description')}
      />

      {companyQuery.isPending && <LoadingState label={t('CompanySettingsPage.loadingLabel')} />}
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
  const { t } = useTranslation('companySettings')
  const visibleTabs = visibleTabsFor(company, t)
  const activeTab = visibleTabs.find((tabItem) => tabItem.value === tab)

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
        {visibleTabs.map((tabItem) => (
          <Tab
            key={tabItem.value}
            value={tabItem.value}
            label={tabItem.label}
            id={`company-settings-tab-${tabItem.value}`}
          />
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
