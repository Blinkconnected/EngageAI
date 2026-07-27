import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, TextField } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import LockResetOutlinedIcon from '@mui/icons-material/LockResetOutlined'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllDepartmentsQuery } from '../departments/api'
import { AgentCreateDialog } from './AgentCreateDialog'
import { AgentEditDialog } from './AgentEditDialog'
import { AgentRemovalDialog } from './AgentRemovalDialog'
import { AgentResetPasswordDialog } from './AgentResetPasswordDialog'
import { AgentRoleDialog } from './AgentRoleDialog'
import { useAgentsQuery } from './api'
import type { Agent, AgentStatus } from './types'

const STATUS_COLOR: Record<AgentStatus, 'success' | 'warning' | 'default'> = {
  online: 'success',
  away: 'warning',
  busy: 'warning',
  offline: 'default',
}

export function AgentsPage() {
  const { t, i18n } = useTranslation('agents')
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('agents.manage')
  const canManageRoles = hasPermission('roles.manage')

  const [search, setSearch] = useState('')
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()
  const agentsQuery = useAgentsQuery({ ...apiParams, search: search || undefined })
  const departmentsQuery = useAllDepartmentsQuery()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [removingAgent, setRemovingAgent] = useState<Agent | null>(null)
  const [resettingPasswordAgent, setResettingPasswordAgent] = useState<Agent | null>(null)
  const [changingRoleAgent, setChangingRoleAgent] = useState<Agent | null>(null)

  const departmentNameById = useMemo(() => {
    const map = new Map<string, string>()
    departmentsQuery.data?.forEach((department) => map.set(department.id, department.name))
    return map
  }, [departmentsQuery.data])

  const columns: GridColDef<Agent>[] = useMemo(
    () => {
      const STATUS_LABEL: Record<AgentStatus, string> = {
        online: t('AgentsPage.statusOnline'),
        away: t('AgentsPage.statusAway'),
        busy: t('AgentsPage.statusBusy'),
        offline: t('AgentsPage.statusOffline'),
      }
      return [
        { field: 'full_name', headerName: t('AgentsPage.columnName'), flex: 1, minWidth: 160 },
        { field: 'email', headerName: t('AgentsPage.columnEmail'), flex: 1, minWidth: 200 },
        {
          field: 'title',
          headerName: t('AgentsPage.columnTitle'),
          flex: 1,
          minWidth: 140,
          valueGetter: (_value, row) => row.title ?? t('AgentsPage.emptyValue'),
        },
        {
          field: 'department_id',
          headerName: t('AgentsPage.columnDepartment'),
          flex: 1,
          minWidth: 140,
          valueGetter: (_value, row) =>
            (row.department_id && departmentNameById.get(row.department_id)) ||
            t('AgentsPage.emptyValue'),
        },
        {
          field: 'status',
          headerName: t('AgentsPage.columnStatus'),
          width: 120,
          renderCell: (params) => (
            <Chip
              label={STATUS_LABEL[params.value as AgentStatus]}
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
                headerName: t('AgentsPage.columnActions'),
                width: (canManage ? 130 : 0) + (canManageRoles ? 40 : 0),
                getActions: (params: { row: Agent }) => [
                  ...(canManage
                    ? [
                        <GridActionsCellItem
                          key="edit"
                          icon={<EditOutlinedIcon fontSize="small" />}
                          label={t('AgentsPage.actionEdit')}
                          onClick={() => setEditingAgent(params.row)}
                        />,
                        <GridActionsCellItem
                          key="reset-password"
                          icon={<LockResetOutlinedIcon fontSize="small" />}
                          label={t('AgentsPage.actionResetPassword')}
                          onClick={() => setResettingPasswordAgent(params.row)}
                        />,
                      ]
                    : []),
                  ...(canManageRoles
                    ? [
                        <GridActionsCellItem
                          key="change-role"
                          icon={<BadgeOutlinedIcon fontSize="small" />}
                          label={t('AgentsPage.actionChangeRole')}
                          onClick={() => setChangingRoleAgent(params.row)}
                        />,
                      ]
                    : []),
                  ...(canManage
                    ? [
                        <GridActionsCellItem
                          key="delete"
                          icon={<DeleteOutlineIcon fontSize="small" />}
                          label={t('AgentsPage.actionDelete')}
                          onClick={() => setRemovingAgent(params.row)}
                        />,
                      ]
                    : []),
                ],
              },
            ]
          : []),
      ]
    },
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canManage, canManageRoles, departmentNameById, t, i18n.language],
  )

  return (
    <>
      <PageHeader
        title={t('AgentsPage.pageTitle')}
        description={t('AgentsPage.pageDescription')}
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              {t('AgentsPage.newAgentButton')}
            </Button>
          )
        }
      />

      <TextField
        label={t('AgentsPage.searchLabel')}
        placeholder={t('AgentsPage.searchPlaceholder')}
        size="small"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value)
          setPage(0)
        }}
        sx={{ mb: 2, width: 320 }}
      />

      {agentsQuery.data?.total === 0 ? (
        <EmptyState
          title={
            search ? t('AgentsPage.emptyStateTitleSearch') : t('AgentsPage.emptyStateTitleDefault')
          }
          description={
            search
              ? t('AgentsPage.emptyStateDescriptionSearch')
              : t('AgentsPage.emptyStateDescriptionDefault')
          }
          action={
            !search &&
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                {t('AgentsPage.newAgentButton')}
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel={t('AgentsPage.dataTableAriaLabel')}
          rows={agentsQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={agentsQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={agentsQuery.isFetching}
          error={agentsQuery.error}
          onRetry={() => agentsQuery.refetch()}
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
          <AgentRemovalDialog agent={removingAgent} onClose={() => setRemovingAgent(null)} />
        </>
      )}

      {canManageRoles && (
        <AgentRoleDialog agent={changingRoleAgent} onClose={() => setChangingRoleAgent(null)} />
      )}
    </>
  )
}
