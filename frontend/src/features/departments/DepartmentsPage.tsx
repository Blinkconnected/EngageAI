import { useMemo, useState } from 'react'
import { Button, Chip, TextField } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllAgentsQuery } from '../agents/api'
import { DepartmentAgentsDialog } from './DepartmentAgentsDialog'
import { DepartmentCreateDialog } from './DepartmentCreateDialog'
import { DepartmentEditDialog } from './DepartmentEditDialog'
import { useDeleteDepartmentMutation, useDepartmentsQuery } from './api'
import type { Department } from './types'

export function DepartmentsPage() {
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('departments.manage')

  const [search, setSearch] = useState('')
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()
  const departmentsQuery = useDepartmentsQuery({ ...apiParams, search: search || undefined })
  const agentsQuery = useAllAgentsQuery()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null)
  const [viewingAgentsDepartment, setViewingAgentsDepartment] = useState<Department | null>(null)
  const [deletingDepartment, setDeletingDepartment] = useState<Department | null>(null)
  const deleteMutation = useDeleteDepartmentMutation()

  const agentCountByDepartment = useMemo(() => {
    const counts = new Map<string, number>()
    agentsQuery.data?.forEach((agent) => {
      if (!agent.department_id) return
      counts.set(agent.department_id, (counts.get(agent.department_id) ?? 0) + 1)
    })
    return counts
  }, [agentsQuery.data])

  const deletingDepartmentAgentCount = deletingDepartment
    ? (agentCountByDepartment.get(deletingDepartment.id) ?? 0)
    : 0

  const columns: GridColDef<Department>[] = useMemo(
    () => [
      { field: 'name', headerName: 'Name', flex: 1, minWidth: 160 },
      {
        field: 'description',
        headerName: 'Description',
        flex: 1.5,
        minWidth: 200,
        valueGetter: (_value, row) => row.description ?? '—',
      },
      {
        field: 'agent_count',
        headerName: 'Agents',
        width: 100,
        valueGetter: (_value, row) => agentCountByDepartment.get(row.id) ?? 0,
        renderCell: (params) => (
          <Chip
            icon={<GroupOutlinedIcon fontSize="small" />}
            label={params.value}
            size="small"
            variant="outlined"
            aria-label={`View ${params.value} agent(s) in ${(params.row as Department).name}`}
            onClick={() => setViewingAgentsDepartment(params.row as Department)}
          />
        ),
      },
      {
        field: 'is_active',
        headerName: 'Status',
        width: 110,
        renderCell: (params) => (
          <Chip
            label={params.value ? 'Active' : 'Inactive'}
            size="small"
            color={params.value ? 'success' : 'default'}
          />
        ),
      },
      ...(canManage
        ? [
            {
              field: 'actions',
              type: 'actions' as const,
              headerName: 'Actions',
              width: 80,
              getActions: (params: { row: Department }) => [
                <GridActionsCellItem
                  key="edit"
                  icon={<EditOutlinedIcon fontSize="small" />}
                  label="Edit"
                  onClick={() => setEditingDepartment(params.row)}
                />,
                <GridActionsCellItem
                  key="delete"
                  icon={<DeleteOutlineIcon fontSize="small" />}
                  label="Delete"
                  onClick={() => setDeletingDepartment(params.row)}
                />,
              ],
            },
          ]
        : []),
    ],
    [canManage, agentCountByDepartment],
  )

  return (
    <>
      <PageHeader
        title="Departments"
        description="Organize agents into departments to prepare for routing, queues and reporting."
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              New department
            </Button>
          )
        }
      />

      <TextField
        label="Search departments"
        placeholder="Name or description"
        size="small"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value)
          setPage(0)
        }}
        sx={{ mb: 2, width: 320 }}
      />

      {departmentsQuery.data?.total === 0 ? (
        <EmptyState
          title={search ? 'No departments found' : 'No departments yet'}
          description={
            search
              ? 'Try a different search.'
              : 'Create your first department to start organizing agents.'
          }
          action={
            !search &&
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                New department
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel="Departments"
          rows={departmentsQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={departmentsQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={departmentsQuery.isFetching}
          error={departmentsQuery.error}
          onRetry={() => departmentsQuery.refetch()}
        />
      )}

      {canManage && (
        <>
          <DepartmentCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
          <DepartmentEditDialog
            department={editingDepartment}
            onClose={() => setEditingDepartment(null)}
          />
          <ConfirmDialog
            open={Boolean(deletingDepartment)}
            title="Remove department"
            description={
              deletingDepartmentAgentCount > 0
                ? `Remove ${deletingDepartment?.name ?? ''}? ${deletingDepartmentAgentCount} agent(s) currently assigned to it will be unassigned.`
                : `Remove ${deletingDepartment?.name ?? ''}? This cannot be undone.`
            }
            confirmLabel="Remove"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingDepartment) {
                deleteMutation.mutate(deletingDepartment.id, {
                  onSuccess: () => setDeletingDepartment(null),
                })
              }
            }}
            onClose={() => setDeletingDepartment(null)}
          />
        </>
      )}
      <DepartmentAgentsDialog
        department={viewingAgentsDepartment}
        onClose={() => setViewingAgentsDepartment(null)}
      />
    </>
  )
}
