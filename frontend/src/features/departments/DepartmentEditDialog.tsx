import { useState } from 'react'
import { FormControlLabel, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useUpdateDepartmentMutation } from './api'
import type { Department } from './types'

export function DepartmentEditDialog({
  department,
  onClose,
}: {
  department: Department | null
  onClose: () => void
}) {
  if (!department) return null
  // Keying on department.id remounts fresh whenever a different
  // department is opened, so fields simply initialize from props.
  return <DepartmentEditDialogFields department={department} onClose={onClose} key={department.id} />
}

function DepartmentEditDialogFields({
  department,
  onClose,
}: {
  department: Department
  onClose: () => void
}) {
  const [name, setName] = useState(department.name)
  const [description, setDescription] = useState(department.description ?? '')
  const [isActive, setIsActive] = useState(department.is_active)

  const updateMutation = useUpdateDepartmentMutation()

  function handleSubmit() {
    updateMutation.mutate(
      {
        departmentId: department.id,
        payload: { name, description: description || null, is_active: isActive },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title={`Edit ${department.name}`}
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
      />
      <TextField
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
      <FormControlLabel
        control={
          <Switch checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
        }
        label="Active"
      />
    </FormDialog>
  )
}
