import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  confirmColor?: 'primary' | 'error'
  isConfirming?: boolean
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  confirmColor = 'primary',
  isConfirming = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const { t } = useTranslation('shared')
  const resolvedConfirmLabel = confirmLabel ?? t('ConfirmDialog.confirmButton')

  return (
    <Dialog open={open} onClose={onClose} aria-labelledby="confirm-dialog-title">
      <DialogTitle id="confirm-dialog-title">{title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{description}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isConfirming}>
          {t('ConfirmDialog.cancelButton')}
        </Button>
        <Button onClick={onConfirm} color={confirmColor} disabled={isConfirming} autoFocus>
          {resolvedConfirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
