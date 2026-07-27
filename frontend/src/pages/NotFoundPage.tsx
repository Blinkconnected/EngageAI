import { Box, Button, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export function NotFoundPage() {
  const { t } = useTranslation('pages')
  return (
    <Box sx={{ textAlign: 'center', mt: 8 }}>
      <Typography variant="h3" sx={{ fontWeight: 700 }} gutterBottom>
        {t('NotFoundPage.errorCode')}
      </Typography>
      <Typography variant="body1" color="text.secondary" gutterBottom>
        {t('NotFoundPage.description')}
      </Typography>
      <Button component={RouterLink} to="/" variant="contained" sx={{ mt: 2 }}>
        {t('NotFoundPage.backButton')}
      </Button>
    </Box>
  )
}
