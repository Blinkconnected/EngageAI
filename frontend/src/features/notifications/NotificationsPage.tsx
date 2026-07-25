import { useState } from 'react'
import { Tab, Tabs } from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { NotificationHistoryPanel } from './NotificationHistoryPanel'
import { NotificationPreferencesPanel } from './NotificationPreferencesPanel'

export function NotificationsPage() {
  const [tab, setTab] = useState<'history' | 'preferences'>('history')

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Everything you've been notified about, and how you'd like to hear about it."
      />

      <Tabs
        value={tab}
        onChange={(_event, value) => setTab(value)}
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        <Tab label="History" value="history" />
        <Tab label="Preferences" value="preferences" />
      </Tabs>

      {tab === 'history' && <NotificationHistoryPanel />}
      {tab === 'preferences' && <NotificationPreferencesPanel />}
    </>
  )
}
