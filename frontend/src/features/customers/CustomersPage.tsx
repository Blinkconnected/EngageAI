import { useMemo, useState } from 'react'
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
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()

  const customersQuery = useCustomersQuery({ ...apiParams, search: search || undefined })

  const columns: GridColDef<Customer>[] = useMemo(
    () => [
      { field: 'full_name', headerName: 'Name', flex: 1, minWidth: 180 },
      {
        field: 'email',
        headerName: 'Email',
        flex: 1,
        minWidth: 200,
        valueGetter: (_value, row) => row.email ?? '—',
      },
      {
        field: 'phone',
        headerName: 'Phone',
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => row.phone ?? '—',
      },
      {
        field: 'tags',
        headerName: 'Tags',
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => row.tags.join(', ') || '—',
      },
    ],
    [],
  )

  return (
    <>
      <PageHeader title="Customers" description="Everyone who has reached out to your company." />

      <TextField
        label="Search by name or email"
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
          title="No customers found"
          description={
            search
              ? 'Try a different search.'
              : 'Customers appear here automatically as conversations come in.'
          }
        />
      ) : (
        <DataTable
          ariaLabel="Customers"
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
        />
      )}
    </>
  )
}
