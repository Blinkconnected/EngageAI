import { useMemo, useState } from 'react'
import { Button, Chip, TextField } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
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
  const { t, i18n } = useTranslation('departments')
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
      { field: 'name', headerName: t('DepartmentsPage.columnName'), flex: 1, minWidth: 160 },
      {
        field: 'description',
        headerName: t('DepartmentsPage.columnDescription'),
        flex: 1.5,
        minWidth: 200,
        valueGetter: (_value, row) => row.description ?? t('DepartmentsPage.noValuePlaceholder'),
      },
      {
        field: 'agent_count',
        headerName: t('DepartmentsPage.columnAgents'),
        width: 100,
        valueGetter: (_value, row) => agentCountByDepartment.get(row.id) ?? 0,
        renderCell: (params) => (
          <Chip
            icon={<GroupOutlinedIcon fontSize="small" />}
            label={params.value}
            size="small"
            variant="outlined"
            aria-label={t('DepartmentsPage.agentCountAriaLabel', {
              count: params.value,
              name: (params.row as Department).name,
            })}
            onClick={() => setViewingAgentsDepartment(params.row as Department)}
          />
        ),
      },
      {
        field: 'is_active',
        headerName: t('DepartmentsPage.columnStatus'),
        width: 110,
        renderCell: (params) => (
          <Chip
            label={
              params.value ? t('DepartmentsPage.statusActive') : t('DepartmentsPage.statusInactive')
            }
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
              headerName: t('DepartmentsPage.columnActions'),
              width: 80,
              getActions: (params: { row: Department }) => [
                <GridActionsCellItem
                  key="edit"
                  icon={<EditOutlinedIcon fontSize="small" />}
                  label={t('DepartmentsPage.editAction')}
                  onClick={() => setEditingDepartment(params.row)}
                />,
                <GridActionsCellItem
                  key="delete"
                  icon={<DeleteOutlineIcon fontSize="small" />}
                  label={t('DepartmentsPage.deleteAction')}
                  onClick={() => setDeletingDepartment(params.row)}
                />,
              ],
            },
          ]
        : []),
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canManage, agentCountByDepartment, t, i18n.language],
  )

  return (
    <>
      <PageHeader
        title={t('DepartmentsPage.pageTitle')}
        description={t('DepartmentsPage.pageDescription')}
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              {t('DepartmentsPage.newDepartmentButton')}
            </Button>
          )
        }
      />

      <TextField
        label={t('DepartmentsPage.searchLabel')}
        placeholder={t('DepartmentsPage.searchPlaceholder')}
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
          title={
            search ? t('DepartmentsPage.emptyTitleSearch') : t('DepartmentsPage.emptyTitleNoSearch')
          }
          description={
            search
              ? t('DepartmentsPage.emptyDescriptionSearch')
              : t('DepartmentsPage.emptyDescriptionNoSearch')
          }
          action={
            !search &&
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                {t('DepartmentsPage.newDepartmentButton')}
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel={t('DepartmentsPage.dataTableAriaLabel')}
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
            title={t('DepartmentsPage.deleteDialogTitle')}
            description={
              deletingDepartmentAgentCount > 0
                ? t('DepartmentsPage.deleteDialogDescriptionWithAgents', {
                    name: deletingDepartment?.name ?? '',
                    count: deletingDepartmentAgentCount,
                  })
                : t('DepartmentsPage.deleteDialogDescriptionNoAgents', {
                    name: deletingDepartment?.name ?? '',
                  })
            }
            confirmLabel={t('DepartmentsPage.deleteDialogConfirmLabel')}
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
