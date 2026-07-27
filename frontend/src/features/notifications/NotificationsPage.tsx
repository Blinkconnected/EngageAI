import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tab, Tabs } from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { NotificationHistoryPanel } from './NotificationHistoryPanel'
import { NotificationPreferencesPanel } from './NotificationPreferencesPanel'

export function NotificationsPage() {
  const { t } = useTranslation('notifications')
  const [tab, setTab] = useState<'history' | 'preferences'>('history')

  return (
    <>
      <PageHeader
        title={t('NotificationsPage.title')}
        description={t('NotificationsPage.description')}
      />

      <Tabs
        value={tab}
        onChange={(_event, value) => setTab(value)}
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        <Tab label={t('NotificationsPage.historyTab')} value="history" />
        <Tab label={t('NotificationsPage.preferencesTab')} value="preferences" />
      </Tabs>

      {tab === 'history' && <NotificationHistoryPanel />}
      {tab === 'preferences' && <NotificationPreferencesPanel />}
    </>
  )
}
