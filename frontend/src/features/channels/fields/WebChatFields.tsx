import { Alert } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function WebChatFields() {
  const { t } = useTranslation('channelsFields')

  return <Alert severity="info">{t('WebChatFields.infoAlert')}</Alert>
}
