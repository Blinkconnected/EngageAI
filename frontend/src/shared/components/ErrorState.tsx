import { Alert, AlertTitle, Button } from '@mui/material'
import { extractErrorMessage } from '../api/errors'

interface ErrorStateProps {
  error: unknown
  title?: string
  onRetry?: () => void
}

export function ErrorState({ error, title = 'Something went wrong', onRetry }: ErrorStateProps) {
  return (
    <Alert
      severity="error"
      action={
        onRetry && (
          <Button color="inherit" size="small" onClick={onRetry}>
            Retry
          </Button>
        )
      }
      sx={{ my: 2 }}
    >
      <AlertTitle>{title}</AlertTitle>
      {extractErrorMessage(error)}
    </Alert>
  )
}
