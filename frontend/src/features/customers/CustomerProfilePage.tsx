import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Box, Button, Chip, IconButton, Stack, Tab, Tabs, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useIsErpEnabled } from '../company/api'
import { CustomerErpPanel } from '../erp/CustomerErpPanel'
import { useCustomerQuery } from './api'
import { CustomerEditDialog } from './CustomerEditDialog'
import { CustomerTimelinePanel } from './CustomerTimelinePanel'

export function CustomerProfilePage() {
  const { customerId } = useParams<{ customerId: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'timeline' | 'erp'>('timeline')
  const [editing, setEditing] = useState(false)
  const { hasPermission } = usePermissions()
  const isErpEnabled = useIsErpEnabled()

  const customerQuery = useCustomerQuery(customerId)

  if (customerQuery.isPending) return <LoadingState label="Loading customer…" />
  if (customerQuery.isError) {
    return <ErrorState error={customerQuery.error} onRetry={() => customerQuery.refetch()} />
  }

  const customer = customerQuery.data

  return (
    <>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
        <IconButton
          onClick={() => navigate('/customers')}
          aria-label="Back to customers"
          sx={{ mt: 0.5 }}
        >
          <ArrowBackIcon />
        </IconButton>
        <Box sx={{ flexGrow: 1 }}>
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
        </Box>
      </Stack>

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
        {isErpEnabled && <Tab label="ERPNext" value="erp" />}
      </Tabs>

      {tab === 'erp' && isErpEnabled ? (
        <CustomerErpPanel customerId={customer.id} />
      ) : (
        <CustomerTimelinePanel customerId={customer.id} />
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
