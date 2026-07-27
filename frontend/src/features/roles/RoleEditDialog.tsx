import { useState } from 'react'
import { Alert, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { extractErrorMessage } from '../../shared/api/errors'
import { PermissionChecklist } from './PermissionChecklist'
import { useUpdateRoleMutation, usePermissionsQuery } from './api'
import type { Role } from './types'

export function RoleEditDialog({ role, onClose }: { role: Role | null; onClose: () => void }) {
  if (!role) return null
  // Keying on role.id remounts fresh whenever a different role is opened
  // (see QueueEditDialog/QueueEditDialogFields for the same pattern).
  return <RoleEditDialogFields role={role} onClose={onClose} key={role.id} />
}

function RoleEditDialogFields({ role, onClose }: { role: Role; onClose: () => void }) {
  const { t } = useTranslation('roles')
  const [name, setName] = useState(role.name)
  const [description, setDescription] = useState(role.description ?? '')
  const [permissionCodes, setPermissionCodes] = useState<Set<string>>(
    () => new Set(role.permission_codes),
  )

  const permissionsQuery = usePermissionsQuery()
  const updateMutation = useUpdateRoleMutation()

  const isOwner = role.is_system && role.name === 'Owner'

  function handleSubmit() {
    updateMutation.mutate(
      {
        roleId: role.id,
        payload: {
          name,
          description: description || null,
          permission_codes: [...permissionCodes],
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={t('RoleEditDialog.title', { name: role.name })}
      submitLabel={t('RoleEditDialog.submitLabel')}
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label={t('RoleEditDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus={!role.is_system}
        disabled={role.is_system}
        helperText={role.is_system ? t('RoleEditDialog.systemRoleNameHelperText') : undefined}
      />
      <TextField
        label={t('RoleEditDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
        // Name is disabled for a system role — focus lands here instead,
        // the first field actually editable in that case.
        autoFocus={role.is_system}
      />
      {isOwner && <Alert severity="info">{t('RoleEditDialog.ownerRoleInfo')}</Alert>}
      {permissionsQuery.isPending && (
        <LoadingState label={t('RoleEditDialog.loadingPermissions')} />
      )}
      {permissionsQuery.data && (
        <PermissionChecklist
          permissions={permissionsQuery.data}
          selected={permissionCodes}
          onChange={setPermissionCodes}
          disabled={isOwner}
        />
      )}
    </FormDialog>
  )
}
