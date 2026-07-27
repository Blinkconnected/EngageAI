import { useState } from 'react'
import { Alert, TextField } from '@mui/material'
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
      title={`Edit ${role.name}`}
      submitLabel="Save changes"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label="Name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
        disabled={role.is_system}
        helperText={role.is_system ? "A system role's name can't be changed." : undefined}
      />
      <TextField
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      {isOwner && (
        <Alert severity="info">
          The Owner role always has every permission and can't be changed.
        </Alert>
      )}
      {permissionsQuery.isPending && <LoadingState label="Loading permissions…" />}
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
