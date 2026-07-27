import { Box, CircularProgress, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function LoadingState({ label }: { label?: string }) {
  const { t } = useTranslation('shared')
  const resolvedLabel = label ?? t('LoadingState.label')

  return (
    <Box
      sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, py: 6 }}
      role="status"
    >
      <CircularProgress aria-label={resolvedLabel} />
      <Typography variant="body2" color="text.secondary">
        {resolvedLabel}
      </Typography>
    </Box>
  )
}
