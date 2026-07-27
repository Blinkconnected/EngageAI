import { useState } from 'react'
import { FormControlLabel, Switch, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useCreateHolidayMutation } from './api'

export function HolidayCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('sla')
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
      title={t('HolidayCreateDialog.dialogTitle')}
      submitLabel={t('HolidayCreateDialog.submitLabel')}
      isSubmitting={createMutation.isPending}
      error={createMutation.error}
      errorMessage={createMutation.error ? extractErrorMessage(createMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={handleClose}
    >
      <TextField
        label={t('HolidayCreateDialog.nameLabel')}
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label={t('HolidayCreateDialog.dateLabel')}
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
        label={t('HolidayCreateDialog.recursAnnuallyLabel')}
      />
    </FormDialog>
  )
}
