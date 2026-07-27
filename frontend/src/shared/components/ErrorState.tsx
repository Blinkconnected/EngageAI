import { Alert, AlertTitle, Button } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../api/errors'

interface ErrorStateProps {
  error: unknown
  title?: string
  onRetry?: () => void
}

export function ErrorState({ error, title, onRetry }: ErrorStateProps) {
  const { t } = useTranslation('shared')
  const resolvedTitle = title ?? t('ErrorState.defaultTitle')

  return (
    <Alert
      severity="error"
      action={
        onRetry && (
          <Button color="inherit" size="small" onClick={onRetry}>
            {t('ErrorState.retryButton')}
          </Button>
        )
      }
      sx={{ my: 2 }}
    >
      <AlertTitle>{resolvedTitle}</AlertTitle>
      {extractErrorMessage(error)}
    </Alert>
  )
}
