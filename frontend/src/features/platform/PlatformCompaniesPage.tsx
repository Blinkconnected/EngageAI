import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useDebouncedValue } from '../../shared/hooks/useDebouncedValue'
import { CompanyFeaturesDialog } from './CompanyFeaturesDialog'
import { useCompaniesQuery, useSetCompanyStatusMutation } from './api'
import type { CompanyOverview, CompanyStatus, SubscriptionStatus } from './types'

const STATUS_COLOR: Record<CompanyStatus, 'default' | 'success' | 'error'> = {
  trial: 'default',
  active: 'success',
  suspended: 'error',
}

const STATUS_OPTIONS: CompanyStatus[] = ['trial', 'active', 'suspended']

const SUBSCRIPTION_COLOR: Record<SubscriptionStatus, 'default' | 'success' | 'warning' | 'error'> = {
  approval_pending: 'warning',
  active: 'success',
  past_due: 'warning',
  suspended: 'error',
  cancelled: 'default',
  expired: 'default',
}

/**
 * The platform operator's console: every company on the installation,
 * with the ability to suspend or reactivate each one.
 *
 * Deliberately shows size counts only — never a company's conversations,
 * messages or customers. That is the product promise the platform tier
 * is built around (see docs/architecture/platform-admin.md), and this
 * page is where it would be most tempting to break it.
 */
export function PlatformCompaniesPage() {
  const { t } = useTranslation('platform')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<CompanyStatus | ''>('')
  const [pending, setPending] = useState<{ company: CompanyOverview; next: CompanyStatus } | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [featuresFor, setFeaturesFor] = useState<CompanyOverview | null>(null)

  const debouncedSearch = useDebouncedValue(search, 300)
  const companiesQuery = useCompaniesQuery({
    page: page + 1,
    page_size: pageSize,
    search: debouncedSearch || undefined,
    status_filter: statusFilter || undefined,
  })
  const statusMutation = useSetCompanyStatusMutation()

  function handleConfirm() {
    if (!pending) return
    setError(null)
    statusMutation.mutate(
      { companyId: pending.company.id, status: pending.next },
      {
        onSuccess: () => setPending(null),
        onError: (mutationError) => {
          setError(extractErrorMessage(mutationError, t('PlatformCompaniesPage.statusErrorFallback')))
          setPending(null)
        },
      },
    )
  }

  const columns: GridColDef<CompanyOverview>[] = [
    { field: 'name', headerName: t('PlatformCompaniesPage.columnName'), flex: 1.4, minWidth: 180 },
    { field: 'slug', headerName: t('PlatformCompaniesPage.columnSlug'), flex: 1, minWidth: 140 },
    {
      field: 'status',
      headerName: t('PlatformCompaniesPage.columnStatus'),
      width: 130,
      renderCell: (params) => (
        <Chip
          size="small"
          label={t(`PlatformCompaniesPage.status.${params.value as CompanyStatus}`)}
          color={STATUS_COLOR[params.value as CompanyStatus]}
        />
      ),
    },
    {
      field: 'plan_name',
      headerName: t('PlatformCompaniesPage.columnPlan'),
      flex: 1,
      minWidth: 160,
      sortable: false,
      renderCell: (params) => {
        const status = params.row.subscription_status
        if (status === null) {
          return (
            <Typography variant="body2" color="text.secondary">
              {t('PlatformCompaniesPage.noSubscription')}
            </Typography>
          )
        }
        return (
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Typography variant="body2">{params.row.plan_name}</Typography>
            <Chip
              size="small"
              variant="outlined"
              color={SUBSCRIPTION_COLOR[status]}
              label={t(`PlatformCompaniesPage.subscriptionStatus.${status}`)}
            />
          </Stack>
        )
      },
    },
    {
      field: 'user_count',
      headerName: t('PlatformCompaniesPage.columnUsers'),
      width: 100,
      type: 'number',
    },
    {
      field: 'agent_count',
      headerName: t('PlatformCompaniesPage.columnAgents'),
      width: 100,
      type: 'number',
    },
    {
      field: 'conversation_count',
      headerName: t('PlatformCompaniesPage.columnConversations'),
      width: 150,
      type: 'number',
    },
    {
      field: 'actions',
      headerName: t('PlatformCompaniesPage.columnActions'),
      width: 220,
      sortable: false,
      renderCell: (params) => {
        const suspended = params.row.status === 'suspended'
        return (
          <Stack direction="row" spacing={1}>
            <Button size="small" variant="outlined" onClick={() => setFeaturesFor(params.row)}>
              {t('PlatformCompaniesPage.featuresButton')}
            </Button>
            <Button
              size="small"
              color={suspended ? 'success' : 'error'}
              variant="outlined"
              onClick={() =>
                setPending({ company: params.row, next: suspended ? 'active' : 'suspended' })
              }
            >
              {suspended
                ? t('PlatformCompaniesPage.reactivateButton')
                : t('PlatformCompaniesPage.suspendButton')}
            </Button>
          </Stack>
        )
      },
    },
  ]

  return (
    <>
      <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
        {t('PlatformCompaniesPage.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('PlatformCompaniesPage.description')}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          size="small"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(0)
          }}
          placeholder={t('PlatformCompaniesPage.searchPlaceholder')}
          slotProps={{ htmlInput: { 'aria-label': t('PlatformCompaniesPage.searchAriaLabel') } }}
          sx={{ minWidth: 260 }}
        />
        <TextField
          select
          size="small"
          label={t('PlatformCompaniesPage.statusFilterLabel')}
          value={statusFilter}
          onChange={(event) => {
            setStatusFilter(event.target.value as CompanyStatus | '')
            setPage(0)
          }}
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">{t('PlatformCompaniesPage.allStatusesOption')}</MenuItem>
          {STATUS_OPTIONS.map((status) => (
            <MenuItem key={status} value={status}>
              {t(`PlatformCompaniesPage.status.${status}`)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      {companiesQuery.data?.total === 0 && !companiesQuery.isError ? (
        <EmptyState
          title={t('PlatformCompaniesPage.emptyTitle')}
          description={t('PlatformCompaniesPage.emptyDescription')}
        />
      ) : (
        <Box>
          <DataTable
            ariaLabel={t('PlatformCompaniesPage.tableAriaLabel')}
            rows={companiesQuery.data?.items ?? []}
            columns={columns}
            getRowId={(row) => row.id}
            rowCount={companiesQuery.data?.total ?? 0}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={(next) => {
              setPageSize(next)
              setPage(0)
            }}
            loading={companiesQuery.isFetching}
            error={companiesQuery.isError ? companiesQuery.error : undefined}
            onRetry={() => void companiesQuery.refetch()}
          />
        </Box>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.next === 'suspended'
            ? t('PlatformCompaniesPage.confirmSuspendTitle')
            : t('PlatformCompaniesPage.confirmReactivateTitle')
        }
        description={
          pending?.next === 'suspended'
            ? t('PlatformCompaniesPage.confirmSuspendDescription', {
                companyName: pending?.company.name ?? '',
              })
            : t('PlatformCompaniesPage.confirmReactivateDescription', {
                companyName: pending?.company.name ?? '',
              })
        }
        confirmLabel={
          pending?.next === 'suspended'
            ? t('PlatformCompaniesPage.suspendButton')
            : t('PlatformCompaniesPage.reactivateButton')
        }
        confirmColor={pending?.next === 'suspended' ? 'error' : 'primary'}
        isConfirming={statusMutation.isPending}
        onConfirm={handleConfirm}
        onClose={() => setPending(null)}
      />

      <CompanyFeaturesDialog company={featuresFor} onClose={() => setFeaturesFor(null)} />
    </>
  )
}
