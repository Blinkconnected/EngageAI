import { Stack } from '@mui/material'
import { ErpEnableToggle } from '../../company/panels/ErpEnableToggle'
import { ErpConnectionPanel } from '../../erp/ErpConnectionPanel'
import type { Company } from '../../company/types'

export function ErpIntegrationStep({ company }: { company: Company }) {
  return (
    <Stack spacing={3}>
      <ErpEnableToggle company={company} />
      {company.settings.erp?.enabled && <ErpConnectionPanel />}
    </Stack>
  )
}
