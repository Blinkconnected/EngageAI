import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Button, Chip, Stack, Tab, Tabs, Typography } from '@mui/material'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { CustomerErpPanel } from '../erp/CustomerErpPanel'
import { useCustomerQuery } from './api'
import { CustomerEditDialog } from './CustomerEditDialog'
import { CustomerTimelinePanel } from './CustomerTimelinePanel'

export function CustomerProfilePage() {
  const { customerId } = useParams<{ customerId: string }>()
  const [tab, setTab] = useState<'timeline' | 'erp'>('timeline')
  const [editing, setEditing] = useState(false)
  const { hasPermission } = usePermissions()

  const customerQuery = useCustomerQuery(customerId)

  if (customerQuery.isPending) return <LoadingState label="Loading customer…" />
  if (customerQuery.isError) {
    return <ErrorState error={customerQuery.error} onRetry={() => customerQuery.refetch()} />
  }

  const customer = customerQuery.data

  return (
    <>
      <PageHeader
        title={customer.full_name}
        description={[customer.email, customer.phone].filter(Boolean).join(' · ') || undefined}
        actions={
          hasPermission('customers.manage') && (
            <Button variant="outlined" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )
        }
      />

      {customer.tags.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap' }}>
          {customer.tags.map((tag) => (
            <Chip key={tag} label={tag} size="small" />
          ))}
        </Stack>
      )}

      {customer.notes && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {customer.notes}
        </Typography>
      )}

      <Tabs
        value={tab}
        onChange={(_event, value) => setTab(value)}
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        <Tab label="Timeline" value="timeline" />
        <Tab label="ERPNext" value="erp" />
      </Tabs>

      {tab === 'timeline' ? (
        <CustomerTimelinePanel customerId={customer.id} />
      ) : (
        <CustomerErpPanel customerId={customer.id} />
      )}

      {hasPermission('customers.manage') && (
        <CustomerEditDialog
          customer={editing ? customer : null}
          onClose={() => setEditing(false)}
        />
      )}
    </>
  )
}
