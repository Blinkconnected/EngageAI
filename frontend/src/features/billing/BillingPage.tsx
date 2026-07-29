import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { LoadingState } from '../../shared/components/LoadingState'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import {
  useBillingOverviewQuery,
  useCancelSubscriptionMutation,
  useSubscribeMutation,
} from './api'
import type { SubscriptionStatus } from './types'

const STATUS_COLOR: Record<SubscriptionStatus, 'default' | 'success' | 'warning' | 'error'> = {
  approval_pending: 'warning',
  active: 'success',
  past_due: 'warning',
  suspended: 'error',
  cancelled: 'default',
  expired: 'default',
}

/**
 * A company's own subscription: what they're on, what it costs, what
 * they've paid, and how to change it.
 *
 * Subscribing hands off to PayPal — the subscription is not active until
 * PayPal confirms the customer approved it, so this page says so rather
 * than claiming success the moment the button is clicked.
 */
export function BillingPage() {
  const { t } = useTranslation('billing')
  const { hasPermission } = usePermissions()
  const overviewQuery = useBillingOverviewQuery()
  const subscribeMutation = useSubscribeMutation()
  const cancelMutation = useCancelSubscriptionMutation()
  const [error, setError] = useState<string | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)

  const canManage = hasPermission('billing.manage')

  if (overviewQuery.isPending) return <LoadingState />
  if (overviewQuery.isError) {
    return (
      <Alert
        severity="error"
        action={
          <Button size="small" onClick={() => void overviewQuery.refetch()}>
            {t('BillingPage.retry')}
          </Button>
        }
      >
        {t('BillingPage.loadError')}
      </Alert>
    )
  }

  const { is_configured: isConfigured, subscription, plans, payments } = overviewQuery.data

  function handleSubscribe(planId: string) {
    setError(null)
    subscribeMutation.mutate(planId, {
      onSuccess: (created) => {
        // Straight to PayPal. The approval link is the whole point of
        // the call — holding the customer on this page to click a
        // second time would just be a step that can be abandoned.
        if (created.approval_url) window.location.assign(created.approval_url)
      },
      onError: (mutationError) =>
        setError(extractErrorMessage(mutationError, t('BillingPage.subscribeError'))),
    })
  }

  function handleCancel() {
    setError(null)
    cancelMutation.mutate(null, {
      onSuccess: () => setIsCancelling(false),
      onError: (mutationError) => {
        setError(extractErrorMessage(mutationError, t('BillingPage.cancelError')))
        setIsCancelling(false)
      },
    })
  }

  return (
    <>
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
        {t('BillingPage.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('BillingPage.description')}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {!isConfigured && <Alert severity="info">{t('BillingPage.notConfigured')}</Alert>}

      {isConfigured && subscription && (
        <Card variant="outlined" sx={{ mb: 3 }}>
          <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
              <Typography variant="h6" component="h2">
                {subscription.plan_name}
              </Typography>
              <Chip
                size="small"
                color={STATUS_COLOR[subscription.status]}
                label={t(`BillingPage.subscriptionStatus.${subscription.status}`)}
              />
            </Stack>
            <Typography variant="body1">
              {subscription.currency} {subscription.amount} /{' '}
              {t(`BillingPage.interval.${subscription.interval}`)}
            </Typography>
            {subscription.current_period_end && (
              <Typography variant="body2" color="text.secondary">
                {t('BillingPage.renewsOn', {
                  date: new Date(subscription.current_period_end).toLocaleDateString(),
                })}
              </Typography>
            )}

            {subscription.status === 'approval_pending' && subscription.approval_url && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                {t('BillingPage.awaitingApproval')}{' '}
                <Link href={subscription.approval_url}>{t('BillingPage.finishInPayPal')}</Link>
              </Alert>
            )}
            {subscription.status === 'past_due' && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                {t('BillingPage.pastDue', { count: subscription.failed_payment_count })}
              </Alert>
            )}
            {subscription.status === 'suspended' && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {t('BillingPage.suspended')}
              </Alert>
            )}

            {canManage && subscription.status !== 'cancelled' && (
              <Button
                size="small"
                color="error"
                sx={{ mt: 2 }}
                onClick={() => setIsCancelling(true)}
              >
                {t('BillingPage.cancelButton')}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {isConfigured && !subscription && plans.length === 0 && (
        <EmptyState
          title={t('BillingPage.noPlansTitle')}
          description={t('BillingPage.noPlansDescription')}
        />
      )}

      {isConfigured && !subscription && plans.length > 0 && (
        <>
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            {t('BillingPage.choosePlan')}
          </Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 3 }}>
            {plans.map((plan) => (
              <Card key={plan.id} variant="outlined" sx={{ flex: 1 }}>
                <CardContent>
                  <Typography variant="h6" component="h3">
                    {plan.name}
                  </Typography>
                  <Typography variant="h5" sx={{ my: 1 }}>
                    {plan.currency} {plan.amount}
                    <Typography component="span" variant="body2" color="text.secondary">
                      {' '}
                      / {t(`BillingPage.interval.${plan.interval}`)}
                    </Typography>
                  </Typography>
                  {plan.description && (
                    <Typography variant="body2" color="text.secondary">
                      {plan.description}
                    </Typography>
                  )}
                  {canManage && (
                    <Button
                      variant="contained"
                      fullWidth
                      sx={{ mt: 2 }}
                      disabled={!plan.is_purchasable || subscribeMutation.isPending}
                      onClick={() => handleSubscribe(plan.id)}
                    >
                      {t('BillingPage.subscribeButton')}
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </Stack>
          {!canManage && <Alert severity="info">{t('BillingPage.needsOwner')}</Alert>}
        </>
      )}

      {isConfigured && payments.length > 0 && (
        <>
          <Divider sx={{ my: 3 }} />
          <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
            {t('BillingPage.paymentHistory')}
          </Typography>
          {/* A plain table, not the paginated DataTable the rest of the
              app uses: the backend caps this list at 50, so it always
              arrives whole. There is no page to turn, and wiring
              server-pagination props to handlers that can never fire
              would be machinery pretending to do something. */}
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" aria-label={t('BillingPage.paymentsTableAriaLabel')}>
              <TableHead>
                <TableRow>
                  <TableCell>{t('BillingPage.columnDate')}</TableCell>
                  <TableCell>{t('BillingPage.columnAmount')}</TableCell>
                  <TableCell>{t('BillingPage.columnStatus')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {payments.map((payment) => (
                  <TableRow key={payment.id}>
                    <TableCell>{new Date(payment.occurred_at).toLocaleDateString()}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {payment.currency} {payment.amount}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={t(`BillingPage.paymentStatus.${payment.status}`)}
                        color={payment.status === 'completed' ? 'success' : 'default'}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}

      <ConfirmDialog
        open={isCancelling}
        title={t('BillingPage.confirmCancelTitle')}
        description={t('BillingPage.confirmCancelDescription')}
        confirmLabel={t('BillingPage.cancelButton')}
        confirmColor="error"
        isConfirming={cancelMutation.isPending}
        onConfirm={handleCancel}
        onClose={() => setIsCancelling(false)}
      />
    </>
  )
}
