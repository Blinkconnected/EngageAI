import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { ErpConnectionPanel } from './ErpConnectionPanel'

export function ErpConfigSettingsPage() {
  const { t } = useTranslation('erp')
  return (
    <>
      <PageHeader
        title={t('ErpConfigSettingsPage.title')}
        description={t('ErpConfigSettingsPage.description')}
      />
      <ErpConnectionPanel />
    </>
  )
}
