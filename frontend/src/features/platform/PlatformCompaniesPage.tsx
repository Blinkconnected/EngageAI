import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Alert,
  Box,
  Chip,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useDebouncedValue } from '../../shared/hooks/useDebouncedValue'
import { CompanyFeaturesDialog } from './CompanyFeaturesDialog'
import { useCompaniesQuery, usePlatformMeQuery, useSetCompanyStatusMutation } from './api'
import type { CompanyOverview, CompanyStatus } from './types'

const STATUS_COLOR: Record<CompanyStatus, 'default' | 'success' | 'error'> = {
  trial: 'default',
  active: 'success',
  suspended: 'error',
}

const STATUS_OPTIONS: CompanyStatus[] = ['trial', 'active', 'suspended']

/**
 * The platform operator's console: every company on the installation,
 * with the ability to suspend or reactivate each one.
 *
 * Deliberately shows size counts only — never a company's conversations,
 * messages or customers. That is the product promise the platform tier
 * is built around (see docs/architecture/platform-admin.md), and this
 * page is where it would be most tempting to break it.
 */
/** The row's actions, behind one control.
 *
 * Four inline buttons needed a 400px column — half the table's width spent on
 * controls, on every row, whether or not anybody was going to press one. They
 * also read as equally weighted, which suspending a company is not.
 *
 * The destructive action is separated below a divider and coloured, so it is
 * reached deliberately rather than by aiming badly. */
function CompanyActionsMenu({
  company,
  readOnly,
  onEditFeatures,
  onChangeStatus,
}: {
  company: CompanyOverview
  readOnly: boolean
  onEditFeatures: () => void
  onChangeStatus: (next: 'active' | 'suspended') => void
}) {
  const { t } = useTranslation('platform')
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const suspended = company.status === 'suspended'
  const close = () => setAnchorEl(null)

  return (
    <>
      <IconButton
        size="small"
        onClick={(e) => setAnchorEl(e.currentTarget)}
        aria-label={t('PlatformCompaniesPage.actionsFor', { name: company.name })}
        aria-haspopup="menu"
        aria-expanded={anchorEl !== null}
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={anchorEl !== null} onClose={close}>
        <MenuItem component={RouterLink} to={`/platform/companies/${company.id}/users`}>
          {t('PlatformCompaniesPage.usersButton')}
        </MenuItem>
        <MenuItem component={RouterLink} to={`/platform/billing/companies/${company.id}`}>
          {t('PlatformCompaniesPage.billingButton')}
        </MenuItem>
        {/* A read-only operator may look at everything and change nothing.
            The API refuses these with 403 — a disabled item with a reason is
            honest, where an enabled one that fails teaches an operator that
            this console's controls are unreliable. */}
        <MenuItem
          disabled={readOnly}
          onClick={() => {
            close()
            onEditFeatures()
          }}
        >
          {readOnly
            ? t('PlatformCompaniesPage.readOnlyAction')
            : t('PlatformCompaniesPage.featuresButton')}
        </MenuItem>
        <Divider />
        <MenuItem
          disabled={readOnly}
          sx={{ color: suspended ? 'success.main' : 'error.main' }}
          onClick={() => {
            close()
            onChangeStatus(suspended ? 'active' : 'suspended')
          }}
        >
          {suspended
            ? t('PlatformCompaniesPage.reactivateButton')
            : t('PlatformCompaniesPage.suspendButton')}
        </MenuItem>
      </Menu>
    </>
  )
}

export function PlatformCompaniesPage() {
  const { t } = useTranslation('platform')
  // Defaults to read-only until the profile answers: assuming the greater
  // authority while the answer is in flight offers buttons that may turn
  // out to be refused.
  const me = usePlatformMeQuery()
  const readOnly = me.data?.read_only ?? true
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
          setError(
            extractErrorMessage(mutationError, t('PlatformCompaniesPage.statusErrorFallback')),
          )
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
      width: 80,
      sortable: false,
      align: 'right',
      headerAlign: 'right',
      renderCell: (params) => (
        <CompanyActionsMenu
          company={params.row}
          readOnly={readOnly}
          onEditFeatures={() => setFeaturesFor(params.row)}
          onChangeStatus={(next) => setPending({ company: params.row, next })}
        />
      ),
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
