import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function Footer() {
  const { t } = useTranslation('shared')
  const year = new Date().getFullYear()

  return (
    <Box sx={{ py: 2, textAlign: 'center' }}>
      <Typography variant="caption" color="text.secondary">
        {t('Footer.copyright', { year })}
      </Typography>
    </Box>
  )
}
