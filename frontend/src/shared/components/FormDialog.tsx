import { useId, type FormEvent, type ReactNode } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
} from '@mui/material'

interface FormDialogProps {
  open: boolean
  title: string
  children: ReactNode
  submitLabel?: string
  isSubmitting?: boolean
  error?: unknown
  errorMessage?: string
  onSubmit: () => void
  onClose: () => void
}

/**
 * Generic modal shell every Create/Edit dialog composes rather than
 * reimplementing — title, form body, submit/cancel actions with
 * submit-pending disabling, and a server-error banner.
 */
export function FormDialog({
  open,
  title,
  children,
  submitLabel = 'Save',
  isSubmitting = false,
  error,
  errorMessage,
  onSubmit,
  onClose,
}: FormDialogProps) {
  const titleId = useId()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSubmit()
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" aria-labelledby={titleId}>
      <DialogTitle id={titleId}>{title}</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error != null && <Alert severity="error">{errorMessage ?? 'Save failed.'}</Alert>}
            {children}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : submitLabel}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
