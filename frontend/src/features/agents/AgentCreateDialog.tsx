import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useCreateAgentMutation } from './api'

export function AgentCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('agents')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  // Off by default. The API has always supported omitting the password —
  // it generates one and emails the agent — but this dialog required the
  // administrator to invent one and then transmit it out of band, over chat
  // or in person, for every agent they ever added.
  const [setPasswordManually, setSetPasswordManually] = useState(false)
  const [password, setPassword] = useState('')
  const [title, setTitle] = useState('')
  const [departmentId, setDepartmentId] = useState('')

  const departmentsQuery = useAllDepartmentsQuery()
  const createMutation = useCreateAgentMutation()

  function reset() {
    setEmail('')
    setFullName('')
    setPassword('')
    setSetPasswordManually(false)
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
        // Omitted entirely rather than sent empty: the backend treats
        // "absent" as "invite them", and an empty string as a password that
        // fails validation.
        password: setPasswordManually ? password : undefined,
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
      <FormControlLabel
        control={
          <Switch
            checked={setPasswordManually}
            onChange={(event) => setSetPasswordManually(event.target.checked)}
          />
        }
        label={t('AgentCreateDialog.setPasswordManuallyLabel')}
      />
      {setPasswordManually ? (
        <TextField
          label={t('AgentCreateDialog.initialPasswordLabel')}
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          fullWidth
          helperText={t('AgentCreateDialog.initialPasswordHelperText')}
        />
      ) : (
        <Alert severity="info">{t('AgentCreateDialog.inviteExplanation')}</Alert>
      )}
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
