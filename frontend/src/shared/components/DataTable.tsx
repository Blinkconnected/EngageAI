import { Box } from '@mui/material'
import { DataGrid, type GridColDef, type GridRowsProp } from '@mui/x-data-grid'

interface DataTableProps<T> {
  rows: T[]
  columns: GridColDef[]
  getRowId: (row: T) => string
  rowCount: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  loading?: boolean
  onRowClick?: (row: T) => void
  ariaLabel: string
}

/**
 * A thin wrapper over MUI X Data Grid configured for server-side pagination
 * against this API's `Page<T>` shape. Sorting/filtering are disabled by
 * default rather than offered as no-op controls, since the backend's list
 * endpoints only accept the specific query params each one documents, not
 * generic sort/filter — see docs/architecture/frontend.md.
 */
export function DataTable<T extends object>({
  rows,
  columns,
  getRowId,
  rowCount,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  loading = false,
  onRowClick,
  ariaLabel,
}: DataTableProps<T>) {
  return (
    <Box sx={{ width: '100%' }} role="region" aria-label={ariaLabel}>
      <DataGrid
        rows={rows as GridRowsProp}
        columns={columns}
        getRowId={(row) => getRowId(row as T)}
        rowCount={rowCount}
        loading={loading}
        paginationMode="server"
        paginationModel={{ page, pageSize }}
        onPaginationModelChange={(model) => {
          if (model.page !== page) onPageChange(model.page)
          if (model.pageSize !== pageSize) onPageSizeChange(model.pageSize)
        }}
        pageSizeOptions={[10, 20, 50, 100]}
        disableColumnMenu
        disableColumnFilter
        disableColumnSorting
        disableRowSelectionOnClick
        autoHeight
        onRowClick={onRowClick ? (params) => onRowClick(params.row as T) : undefined}
        sx={{
          border: 'none',
          '& .MuiDataGrid-row': onRowClick ? { cursor: 'pointer' } : undefined,
        }}
      />
    </Box>
  )
}
