import { useState } from 'react'
import {
  Button,
  Chip,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { RoleCreateDialog } from './RoleCreateDialog'
import { RoleEditDialog } from './RoleEditDialog'
import { RoleMembersDialog } from './RoleMembersDialog'
import { useDeleteRoleMutation, useRolesQuery } from './api'
import type { Role } from './types'

function deleteBlockedReason(
  role: Role,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  if (role.is_system) return t('RolesPage.systemRoleDeleteBlocked')
  if (role.member_count > 0) {
    return role.member_count === 1
      ? t('RolesPage.reassignMemberSingular')
      : t('RolesPage.reassignMemberPlural')
  }
  return null
}

export function RolesPage() {
  const { t } = useTranslation('roles')
  const rolesQuery = useRolesQuery()
  const deleteMutation = useDeleteRoleMutation()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [viewingMembersRole, setViewingMembersRole] = useState<Role | null>(null)
  const [deletingRole, setDeletingRole] = useState<Role | null>(null)

  return (
    <>
      <PageHeader
        title={t('RolesPage.pageTitle')}
        description={t('RolesPage.pageDescription')}
        actions={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            {t('RolesPage.newRoleButton')}
          </Button>
        }
      />

      {rolesQuery.isPending && <LoadingState label={t('RolesPage.loadingRoles')} />}
      {rolesQuery.isError && (
        <ErrorState error={rolesQuery.error} onRetry={() => rolesQuery.refetch()} />
      )}

      {rolesQuery.data && (
        <TableContainer>
          <Table aria-label={t('RolesPage.tableAriaLabel')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('RolesPage.columnName')}</TableCell>
                <TableCell>{t('RolesPage.columnDescription')}</TableCell>
                <TableCell>{t('RolesPage.columnType')}</TableCell>
                <TableCell align="right">{t('RolesPage.columnPermissions')}</TableCell>
                <TableCell align="right">{t('RolesPage.columnMembers')}</TableCell>
                <TableCell align="right">{t('RolesPage.columnActions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rolesQuery.data.map((role) => {
                const blockedReason = deleteBlockedReason(role, t)
                return (
                  <TableRow key={role.id}>
                    <TableCell>{role.name}</TableCell>
                    <TableCell>{role.description ?? t('RolesPage.noValuePlaceholder')}</TableCell>
                    <TableCell>
                      <Chip
                        label={
                          role.is_system ? t('RolesPage.typeSystem') : t('RolesPage.typeCustom')
                        }
                        size="small"
                        color={role.is_system ? 'default' : 'primary'}
                        variant={role.is_system ? 'outlined' : 'filled'}
                      />
                    </TableCell>
                    <TableCell align="right">{role.permission_codes.length}</TableCell>
                    <TableCell align="right">{role.member_count}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
                        <Tooltip title={t('RolesPage.membersTooltip')}>
                          <IconButton
                            size="small"
                            onClick={() => setViewingMembersRole(role)}
                            aria-label={t('RolesPage.viewMembersAriaLabel', { name: role.name })}
                          >
                            <GroupOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={t('RolesPage.editTooltip')}>
                          <IconButton
                            size="small"
                            onClick={() => setEditingRole(role)}
                            aria-label={t('RolesPage.editAriaLabel', { name: role.name })}
                          >
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={blockedReason ?? t('RolesPage.deleteTooltip')}>
                          <span>
                            <IconButton
                              size="small"
                              disabled={blockedReason !== null}
                              onClick={() => setDeletingRole(role)}
                              aria-label={t('RolesPage.deleteAriaLabel', { name: role.name })}
                            >
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <RoleCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
      <RoleEditDialog role={editingRole} onClose={() => setEditingRole(null)} />
      <RoleMembersDialog role={viewingMembersRole} onClose={() => setViewingMembersRole(null)} />
      <ConfirmDialog
        open={Boolean(deletingRole)}
        title={t('RolesPage.removeRoleDialogTitle')}
        description={t('RolesPage.removeRoleDialogDescription', { name: deletingRole?.name ?? '' })}
        confirmLabel={t('RolesPage.removeButton')}
        confirmColor="error"
        isConfirming={deleteMutation.isPending}
        onConfirm={() => {
          if (deletingRole) {
            deleteMutation.mutate(deletingRole.id, { onSuccess: () => setDeletingRole(null) })
          }
        }}
        onClose={() => setDeletingRole(null)}
      />
    </>
  )
}
