import { Box } from '@mui/material'
import { DataGrid, type GridColDef, type GridRowsProp } from '@mui/x-data-grid'
import { ErrorState } from './ErrorState'

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
  /** When set, renders the shared ErrorState in place of the grid — so
   * every DataTable-based list gets consistent "the request failed"
   * feedback for free instead of each page needing to remember to wire
   * it up itself (some previously didn't). */
  error?: unknown
  onRetry?: () => void
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
  error,
  onRetry,
}: DataTableProps<T>) {
  if (error != null) {
    return (
      <Box sx={{ width: '100%' }} role="region" aria-label={ariaLabel}>
        <ErrorState error={error} onRetry={onRetry} />
      </Box>
    )
  }

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
          '& .MuiDataGrid-row': onRowClick
            ? { cursor: 'pointer' }
            : // MUI X's own row-hover background is otherwise always on,
              // implying every table's rows are clickable — suppressed
              // here for a table that isn't, so it doesn't look and feel
              // like the Customers page's genuinely clickable rows.
              { '&:hover': { backgroundColor: 'transparent' } },
        }}
      />
    </Box>
  )
}
