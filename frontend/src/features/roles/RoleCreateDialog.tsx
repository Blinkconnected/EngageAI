import { useState } from 'react'
import { TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { extractErrorMessage } from '../../shared/api/errors'
import { PermissionChecklist } from './PermissionChecklist'
import { useCreateRoleMutation, usePermissionsQuery } from './api'

export function RoleCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('roles')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [permissionCodes, setPermissionCodes] = useState<Set<string>>(new Set())

  const permissionsQuery = usePermissionsQuery()
  const createMutation = useCreateRoleMutation()

  function reset() {
    setName('')
    setDescription('')
    setPermissionCodes(new Set())
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      {
        name,
        description: description || null,
        permission_codes: [...permissionCodes],
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title={t('RoleCreateDialog.title')}
      submitLabel={t('RoleCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('RoleCreateDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('RoleCreateDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      {permissionsQuery.isPending && (
        <LoadingState label={t('RoleCreateDialog.loadingPermissions')} />
      )}
      {permissionsQuery.data && (
        <PermissionChecklist
          permissions={permissionsQuery.data}
          selected={permissionCodes}
          onChange={setPermissionCodes}
        />
      )}
    </FormDialog>
  )
}
