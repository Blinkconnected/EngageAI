import { Alert, Link, Stack, TextField } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { fieldValue, type ChannelFieldsProps } from './types'

export function TelegramFields({ credentials, onChange }: ChannelFieldsProps) {
  const { t } = useTranslation('channelsFields')

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        {t('TelegramFields.alertBeforeLink')}{' '}
        <Link href="https://t.me/botfather" target="_blank" rel="noopener noreferrer">
          {t('TelegramFields.alertLinkText')}
        </Link>{' '}
        {t('TelegramFields.alertAfterLink')} <code>/newbot</code>
        {t('TelegramFields.alertAfterCode')}
      </Alert>
      <TextField
        label={t('TelegramFields.botTokenLabel')}
        type="password"
        value={fieldValue(credentials, 'bot_token')}
        onChange={(event) => onChange({ ...credentials, bot_token: event.target.value })}
        required
        fullWidth
        placeholder={t('TelegramFields.botTokenPlaceholder')}
        helperText={t('TelegramFields.botTokenHelperText')}
      />
    </Stack>
  )
}
