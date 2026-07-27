import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { TextField } from '@mui/material'
import type { GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { useCustomersQuery } from './api'
import type { Customer } from './types'

export function CustomersPage() {
  const { t, i18n } = useTranslation('customers')
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()

  const customersQuery = useCustomersQuery({ ...apiParams, search: search || undefined })

  const columns: GridColDef<Customer>[] = useMemo(
    () => [
      { field: 'full_name', headerName: t('CustomersPage.nameColumn'), flex: 1, minWidth: 180 },
      {
        field: 'email',
        headerName: t('CustomersPage.emailColumn'),
        flex: 1,
        minWidth: 200,
        valueGetter: (_value, row) => row.email ?? '—',
      },
      {
        field: 'phone',
        headerName: t('CustomersPage.phoneColumn'),
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => row.phone ?? '—',
      },
      {
        field: 'tags',
        headerName: t('CustomersPage.tagsColumn'),
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => row.tags.join(', ') || '—',
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  return (
    <>
      <PageHeader title={t('CustomersPage.title')} description={t('CustomersPage.description')} />

      <TextField
        label={t('CustomersPage.searchLabel')}
        size="small"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value)
          setPage(0)
        }}
        sx={{ mb: 2, width: 320 }}
      />

      {customersQuery.data?.total === 0 ? (
        <EmptyState
          title={t('CustomersPage.emptyTitle')}
          description={
            search
              ? t('CustomersPage.emptySearchDescription')
              : t('CustomersPage.emptyDefaultDescription')
          }
        />
      ) : (
        <DataTable
          ariaLabel={t('CustomersPage.tableAriaLabel')}
          rows={customersQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={customersQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={customersQuery.isFetching}
          onRowClick={(row) => navigate(`/customers/${row.id}`)}
          error={customersQuery.error}
          onRetry={() => customersQuery.refetch()}
        />
      )}
    </>
  )
}
