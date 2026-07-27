import { useState } from 'react'
import { TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateDepartmentMutation } from './api'

export function DepartmentCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('departments')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const createMutation = useCreateDepartmentMutation()

  function reset() {
    setName('')
    setDescription('')
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate({ name, description: description || null }, { onSuccess: handleClose })
  }

  return (
    <FormDialog
      open={open}
      title={t('DepartmentCreateDialog.title')}
      submitLabel={t('DepartmentCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('DepartmentCreateDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('DepartmentCreateDialog.descriptionLabel')}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        fullWidth
        multiline
        minRows={2}
      />
    </FormDialog>
  )
}
