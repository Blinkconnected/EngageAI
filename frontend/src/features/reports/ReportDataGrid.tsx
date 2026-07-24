import { Box } from '@mui/material'
import { DataGrid, type GridColDef, type GridRowsProp } from '@mui/x-data-grid'

interface ReportDataGridProps<T extends object> {
  rows: T[]
  columns: GridColDef[]
  getRowId: (row: T) => string
  ariaLabel: string
}

/**
 * Report result sets are small, already-fully-loaded arrays scoped to one
 * date range — not the paginated `Page<T>` shape `DataTable` wraps — so
 * this offers client-side sorting/pagination with no server round-trip,
 * rather than reusing `DataTable`'s server-pagination contract.
 */
export function ReportDataGrid<T extends object>({
  rows,
  columns,
  getRowId,
  ariaLabel,
}: ReportDataGridProps<T>) {
  return (
    <Box sx={{ width: '100%' }} role="region" aria-label={ariaLabel}>
      <DataGrid
        rows={rows as GridRowsProp}
        columns={columns}
        getRowId={(row) => getRowId(row as T)}
        disableColumnMenu
        disableRowSelectionOnClick
        autoHeight
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        pageSizeOptions={[10, 25, 50]}
        sx={{ border: 'none' }}
      />
    </Box>
  )
}
