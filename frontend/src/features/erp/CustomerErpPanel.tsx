import { useState } from 'react'
import { Alert, Button, Stack, TextField } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { ErpRecordCard } from './ErpRecordCard'
import { useErpRecordsQuery, usePullErpRecordsMutation, useSyncCustomerToErpMutation } from './api'

export function CustomerErpPanel({ customerId }: { customerId: string }) {
  const [pullDoctype, setPullDoctype] = useState('')
  const { hasPermission } = usePermissions()
  const canManageErp = hasPermission('erp.manage')

  const recordsQuery = useErpRecordsQuery(customerId)
  const syncMutation = useSyncCustomerToErpMutation(customerId)
  const pullMutation = usePullErpRecordsMutation(customerId)

  if (recordsQuery.isPending) return <LoadingState label="Loading ERP records…" />
  if (recordsQuery.isError) {
    return <ErrorState error={recordsQuery.error} onRetry={() => recordsQuery.refetch()} />
  }

  return (
    <Stack spacing={2}>
      {canManageErp && (
        <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
          <Button
            variant="outlined"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Syncing…' : 'Sync customer to ERP'}
          </Button>
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              label="Doctype"
              value={pullDoctype}
              onChange={(event) => setPullDoctype(event.target.value)}
              placeholder="e.g. Sales Invoice"
            />
            <Button
              variant="outlined"
              disabled={!pullDoctype || pullMutation.isPending}
              onClick={() => pullMutation.mutate(pullDoctype)}
            >
              {pullMutation.isPending ? 'Pulling…' : 'Pull records'}
            </Button>
          </Stack>
        </Stack>
      )}

      {syncMutation.isError && (
        <Alert severity="error">{extractErrorMessage(syncMutation.error)}</Alert>
      )}
      {pullMutation.isError && (
        <Alert severity="error">{extractErrorMessage(pullMutation.error)}</Alert>
      )}

      {recordsQuery.data.length === 0 ? (
        <EmptyState
          title="No ERPNext records yet"
          description="Sync this customer or pull records for a specific doctype to see them here."
        />
      ) : (
        recordsQuery.data.map((record) => <ErpRecordCard key={record.id} record={record} />)
      )}
    </Stack>
  )
}
