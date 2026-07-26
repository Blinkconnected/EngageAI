import { PageHeader } from '../../shared/components/PageHeader'
import { ErpConnectionPanel } from './ErpConnectionPanel'

export function ErpConfigSettingsPage() {
  return (
    <>
      <PageHeader title="ERPNext integration" description="Sync customer records with ERPNext." />
      <ErpConnectionPanel />
    </>
  )
}
