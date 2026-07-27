import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Stack, TextField } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { ErpRecordCard } from './ErpRecordCard'
import { useErpRecordsQuery, usePullErpRecordsMutation, useSyncCustomerToErpMutation } from './api'

export function CustomerErpPanel({ customerId }: { customerId: string }) {
  const { t } = useTranslation('erp')
  const [pullDoctype, setPullDoctype] = useState('')
  const { hasPermission } = usePermissions()
  const canManageErp = hasPermission('erp.manage')

  const recordsQuery = useErpRecordsQuery(customerId)
  const syncMutation = useSyncCustomerToErpMutation(customerId)
  const pullMutation = usePullErpRecordsMutation(customerId)

  if (recordsQuery.isPending) return <LoadingState label={t('CustomerErpPanel.loadingLabel')} />
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
            {syncMutation.isPending
              ? t('CustomerErpPanel.syncingButton')
              : t('CustomerErpPanel.syncButton')}
          </Button>
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              label={t('CustomerErpPanel.doctypeLabel')}
              value={pullDoctype}
              onChange={(event) => setPullDoctype(event.target.value)}
              placeholder={t('CustomerErpPanel.doctypePlaceholder')}
            />
            <Button
              variant="outlined"
              disabled={!pullDoctype || pullMutation.isPending}
              onClick={() => pullMutation.mutate(pullDoctype)}
            >
              {pullMutation.isPending
                ? t('CustomerErpPanel.pullingButton')
                : t('CustomerErpPanel.pullButton')}
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
          title={t('CustomerErpPanel.emptyStateTitle')}
          description={t('CustomerErpPanel.emptyStateDescription')}
        />
      ) : (
        recordsQuery.data.map((record) => <ErpRecordCard key={record.id} record={record} />)
      )}
    </Stack>
  )
}
