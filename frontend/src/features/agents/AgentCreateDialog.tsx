import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useCreateAgentMutation } from './api'

export function AgentCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('agents')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [title, setTitle] = useState('')
  const [departmentId, setDepartmentId] = useState('')

  const departmentsQuery = useAllDepartmentsQuery()
  const createMutation = useCreateAgentMutation()

  function reset() {
    setEmail('')
    setFullName('')
    setPassword('')
    setTitle('')
    setDepartmentId('')
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      {
        email,
        full_name: fullName,
        password,
        title: title || null,
        department_id: departmentId || null,
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title={t('AgentCreateDialog.title')}
      submitLabel={t('AgentCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('AgentCreateDialog.fullNameLabel')}
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('AgentCreateDialog.emailLabel')}
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
        fullWidth
      />
      <TextField
        label={t('AgentCreateDialog.initialPasswordLabel')}
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
        fullWidth
        helperText={t('AgentCreateDialog.initialPasswordHelperText')}
      />
      <TextField
        label={t('AgentCreateDialog.titleLabel')}
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        fullWidth
      />
      <TextField
        label={t('AgentCreateDialog.departmentLabel')}
        select
        value={departmentId}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        disabled={departmentsQuery.isPending}
      >
        <MenuItem value="">{t('AgentCreateDialog.departmentNoneOption')}</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
    </FormDialog>
  )
}
