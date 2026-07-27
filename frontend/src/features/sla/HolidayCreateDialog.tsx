import { useState } from 'react'
import { FormControlLabel, Switch, TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateHolidayMutation } from './api'

export function HolidayCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('')
  const [date, setDate] = useState('')
  const [recursAnnually, setRecursAnnually] = useState(false)

  const createMutation = useCreateHolidayMutation()

  function reset() {
    setName('')
    setDate('')
    setRecursAnnually(false)
    createMutation.reset()
  }

  function handleClose() {
    reset()
    onClose()
  }

  function handleSubmit() {
    createMutation.mutate(
      { name, date, recurs_annually: recursAnnually },
      { onSuccess: handleClose },
    )
  }

  return (
    <FormDialog
      open={open}
      title="New holiday"
      submitLabel="Add holiday"
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
        label="Date"
        type="date"
        value={date}
        onChange={(event) => setDate(event.target.value)}
        required
        fullWidth
        slotProps={{ inputLabel: { shrink: true } }}
      />
      <FormControlLabel
        control={
          <Switch
            checked={recursAnnually}
            onChange={(event) => setRecursAnnually(event.target.checked)}
          />
        }
        label="Repeats every year"
      />
    </FormDialog>
  )
}
