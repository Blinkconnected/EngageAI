import { useState } from 'react'
import { TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { extractErrorMessage } from '../../shared/api/errors'
import { PermissionChecklist } from './PermissionChecklist'
import { useCreateRoleMutation, usePermissionsQuery } from './api'

export function RoleCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
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
      title="New role"
      submitLabel="Create role"
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label="Name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      {permissionsQuery.isPending && <LoadingState label="Loading permissions…" />}
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
