import { Alert } from '@mui/material'

export function WebChatFields() {
  return (
    <Alert severity="info">
      Web Chat needs no external credentials — it's this product's own embeddable chat widget.
      Just save to create it, then use the webhook/session details on the next screen.
    </Alert>
  )
}
