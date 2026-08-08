import { useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { MIN_DELETION_REASON_LENGTH, useRequestConversationDeletionMutation } from './deletionApi'

/**
 * Asking for a conversation to be deleted.
 *
 * Not a confirmation dialog — nothing is destroyed when this closes. It
 * is a short form, and the reason is the whole of it: an administrator
 * reading this in two days will have the customer's name and these
 * sentences, and nothing else, to decide on.
 *
 * The dialog says out loud that nothing happens yet. Somebody who
 * presses a button labelled "Delete" and sees the conversation still
 * there will otherwise press it again.
 */
export function RequestDeletionDialog({
  conversationId,
  open,
  onClose,
}: {
  conversationId: string
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation('conversationsCore')
  const [reason, setReason] = useState('')
  const mutation = useRequestConversationDeletionMutation(conversationId)

  const trimmed = reason.trim()
  const tooShort = trimmed.length < MIN_DELETION_REASON_LENGTH

  function handleClose() {
    setReason('')
    mutation.reset()
    onClose()
  }

  function handleSubmit() {
    if (tooShort) return
    mutation.mutate(trimmed, { onSuccess: handleClose })
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('RequestDeletionDialog.title')}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          {t('RequestDeletionDialog.description')}
        </DialogContentText>

        {mutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => mutation.reset()}>
            {extractErrorMessage(mutation.error, t('RequestDeletionDialog.errorFallback'))}
          </Alert>
        )}

        <TextField
          autoFocus
          fullWidth
          multiline
          minRows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          label={t('RequestDeletionDialog.reasonLabel')}
          placeholder={t('RequestDeletionDialog.reasonPlaceholder')}
          // Only once they have started: an error on an untouched field
          // tells somebody off for not having typed yet.
          error={trimmed.length > 0 && tooShort}
          helperText={t('RequestDeletionDialog.reasonHelp', {
            count: MIN_DELETION_REASON_LENGTH,
          })}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('RequestDeletionDialog.cancel')}</Button>
        <Button
          variant="contained"
          color="error"
          onClick={handleSubmit}
          disabled={tooShort || mutation.isPending}
        >
          {mutation.isPending
            ? t('RequestDeletionDialog.submitting')
            : t('RequestDeletionDialog.submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
