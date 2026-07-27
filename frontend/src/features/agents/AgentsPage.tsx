import { useMemo, useState } from 'react'
import { Button, Chip } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import LockResetOutlinedIcon from '@mui/icons-material/LockResetOutlined'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllDepartmentsQuery } from '../departments/api'
import { AgentCreateDialog } from './AgentCreateDialog'
import { AgentEditDialog } from './AgentEditDialog'
import { AgentResetPasswordDialog } from './AgentResetPasswordDialog'
import { AgentRoleDialog } from './AgentRoleDialog'
import { useAgentsQuery, useDeleteAgentMutation } from './api'
import type { Agent, AgentStatus } from './types'

const STATUS_COLOR: Record<AgentStatus, 'success' | 'warning' | 'default'> = {
  online: 'success',
  away: 'warning',
  busy: 'warning',
  offline: 'default',
}

export function AgentsPage() {
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('agents.manage')
  const canManageRoles = hasPermission('roles.manage')

  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()
  const agentsQuery = useAgentsQuery(apiParams)
  const departmentsQuery = useAllDepartmentsQuery()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [deletingAgent, setDeletingAgent] = useState<Agent | null>(null)
  const [resettingPasswordAgent, setResettingPasswordAgent] = useState<Agent | null>(null)
  const [changingRoleAgent, setChangingRoleAgent] = useState<Agent | null>(null)
  const deleteMutation = useDeleteAgentMutation()

  const departmentNameById = useMemo(() => {
    const map = new Map<string, string>()
    departmentsQuery.data?.forEach((department) => map.set(department.id, department.name))
    return map
  }, [departmentsQuery.data])

  const columns: GridColDef<Agent>[] = useMemo(
    () => [
      { field: 'full_name', headerName: 'Name', flex: 1, minWidth: 160 },
      { field: 'email', headerName: 'Email', flex: 1, minWidth: 200 },
      {
        field: 'title',
        headerName: 'Title',
        flex: 1,
        minWidth: 140,
        valueGetter: (_value, row) => row.title ?? '—',
      },
      {
        field: 'department_id',
        headerName: 'Department',
        flex: 1,
        minWidth: 140,
        valueGetter: (_value, row) =>
          (row.department_id && departmentNameById.get(row.department_id)) || '—',
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 120,
        renderCell: (params) => (
          <Chip
            label={params.value}
            size="small"
            color={STATUS_COLOR[params.value as AgentStatus]}
          />
        ),
      },
      ...(canManage || canManageRoles
        ? [
            {
              field: 'actions',
              type: 'actions' as const,
              headerName: 'Actions',
              width: canManage ? 130 : 40,
              getActions: (params: { row: Agent }) => [
                ...(canManage
                  ? [
                      <GridActionsCellItem
                        key="edit"
                        icon={<EditOutlinedIcon fontSize="small" />}
                        label="Edit"
                        onClick={() => setEditingAgent(params.row)}
                      />,
                      <GridActionsCellItem
                        key="reset-password"
                        icon={<LockResetOutlinedIcon fontSize="small" />}
                        label="Reset password"
                        onClick={() => setResettingPasswordAgent(params.row)}
                      />,
                    ]
                  : []),
                ...(canManageRoles
                  ? [
                      <GridActionsCellItem
                        key="change-role"
                        icon={<BadgeOutlinedIcon fontSize="small" />}
                        label="Change role"
                        onClick={() => setChangingRoleAgent(params.row)}
                      />,
                    ]
                  : []),
                ...(canManage
                  ? [
                      <GridActionsCellItem
                        key="delete"
                        icon={<DeleteOutlineIcon fontSize="small" />}
                        label="Delete"
                        onClick={() => setDeletingAgent(params.row)}
                      />,
                    ]
                  : []),
              ],
            },
          ]
        : []),
    ],
    [canManage, canManageRoles, departmentNameById],
  )

  return (
    <>
      <PageHeader
        title="Agents"
        description="Everyone in your company who can handle conversations."
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              New agent
            </Button>
          )
        }
      />

      {agentsQuery.data?.total === 0 ? (
        <EmptyState
          title="No agents yet"
          description="Create your first agent to start handling conversations."
          action={
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                New agent
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel="Agents"
          rows={agentsQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={agentsQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={agentsQuery.isFetching}
        />
      )}

      {canManage && (
        <>
          <AgentCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
          <AgentEditDialog agent={editingAgent} onClose={() => setEditingAgent(null)} />
          <AgentResetPasswordDialog
            agent={resettingPasswordAgent}
            onClose={() => setResettingPasswordAgent(null)}
          />
          <ConfirmDialog
            open={Boolean(deletingAgent)}
            title="Remove agent"
            description={`Remove ${deletingAgent?.full_name ?? ''} from your company? They will lose access immediately.`}
            confirmLabel="Remove"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingAgent) {
                deleteMutation.mutate(deletingAgent.id, { onSuccess: () => setDeletingAgent(null) })
              }
            }}
            onClose={() => setDeletingAgent(null)}
          />
        </>
      )}

      {canManageRoles && (
        <AgentRoleDialog agent={changingRoleAgent} onClose={() => setChangingRoleAgent(null)} />
      )}
    </>
  )
}
