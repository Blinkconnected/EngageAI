import { useState } from 'react'
import { MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllDepartmentsQuery } from '../departments/api'
import { useCreateAgentMutation } from './api'

export function AgentCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
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
      title="New agent"
      submitLabel="Create agent"
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label="Full name"
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label="Email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
        fullWidth
      />
      <TextField
        label="Initial password"
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
        fullWidth
        helperText="At least 10 characters, including a letter and a digit."
      />
      <TextField
        label="Title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        fullWidth
      />
      <TextField
        label="Department"
        select
        value={departmentId}
        onChange={(event) => setDepartmentId(event.target.value)}
        fullWidth
        disabled={departmentsQuery.isPending}
      >
        <MenuItem value="">None</MenuItem>
        {departmentsQuery.data?.map((department) => (
          <MenuItem key={department.id} value={department.id}>
            {department.name}
          </MenuItem>
        ))}
      </TextField>
    </FormDialog>
  )
}
