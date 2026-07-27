import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { Box, Button, Chip, IconButton, Rating, Stack, Tab, Tabs, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useIsErpEnabled } from '../company/api'
import { CustomerErpPanel } from '../erp/CustomerErpPanel'
import { useCustomerQuery } from './api'
import { CustomerEditDialog } from './CustomerEditDialog'
import { CustomerRatingsPanel } from './CustomerRatingsPanel'
import { CustomerTimelinePanel } from './CustomerTimelinePanel'

export function CustomerProfilePage() {
  const { t } = useTranslation('customers')
  const { customerId } = useParams<{ customerId: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'timeline' | 'erp' | 'rating'>('timeline')
  const [editing, setEditing] = useState(false)
  const { hasPermission } = usePermissions()
  const isErpEnabled = useIsErpEnabled()

  const customerQuery = useCustomerQuery(customerId)

  if (customerQuery.isPending) return <LoadingState label={t('CustomerProfilePage.loadingLabel')} />
  if (customerQuery.isError) {
    return <ErrorState error={customerQuery.error} onRetry={() => customerQuery.refetch()} />
  }

  const customer = customerQuery.data

  return (
    <>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
        <IconButton
          onClick={() => navigate('/customers')}
          aria-label={t('CustomerProfilePage.backAriaLabel')}
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
                  {t('CustomerProfilePage.editButton')}
                </Button>
              )
            }
          />
        </Box>
      </Stack>

      {customer.rating_count > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: 'center' }}>
          <Rating value={customer.rating_average} precision={0.5} readOnly size="small" />
          <Typography variant="body2" color="text.secondary">
            {t('CustomerProfilePage.ratingSummary', {
              average: customer.rating_average,
              count: customer.rating_count,
            })}
          </Typography>
        </Stack>
      )}

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
        <Tab label={t('CustomerProfilePage.timelineTab')} value="timeline" />
        {isErpEnabled && <Tab label={t('CustomerProfilePage.erpTab')} value="erp" />}
        <Tab label={t('CustomerProfilePage.ratingTab')} value="rating" />
      </Tabs>

      {tab === 'erp' && isErpEnabled ? (
        <CustomerErpPanel customerId={customer.id} />
      ) : tab === 'rating' ? (
        <CustomerRatingsPanel customerId={customer.id} />
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
