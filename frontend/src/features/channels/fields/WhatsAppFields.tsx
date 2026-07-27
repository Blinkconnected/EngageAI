import { Alert, Button, Link, Stack, TextField } from '@mui/material'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import { useTranslation } from 'react-i18next'
import { fieldValue, type ChannelFieldsProps } from './types'

function randomToken(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '')
}

export function WhatsAppFields({ credentials, onChange }: ChannelFieldsProps) {
  const { t } = useTranslation('channelsFields')

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        {t('WhatsAppFields.alertBeforeLink')}{' '}
        <Link href="https://developers.facebook.com/apps" target="_blank" rel="noopener noreferrer">
          {t('WhatsAppFields.alertLinkText')}
        </Link>{' '}
        {t('WhatsAppFields.alertAfterLink')}
      </Alert>
      <TextField
        label={t('WhatsAppFields.phoneNumberIdLabel')}
        value={fieldValue(credentials, 'phone_number_id')}
        onChange={(event) => onChange({ ...credentials, phone_number_id: event.target.value })}
        required
        fullWidth
        placeholder={t('WhatsAppFields.phoneNumberIdPlaceholder')}
        helperText={t('WhatsAppFields.phoneNumberIdHelperText')}
      />
      <TextField
        label={t('WhatsAppFields.accessTokenLabel')}
        type="password"
        value={fieldValue(credentials, 'access_token')}
        onChange={(event) => onChange({ ...credentials, access_token: event.target.value })}
        required
        fullWidth
        placeholder={t('WhatsAppFields.accessTokenPlaceholder')}
        helperText={t('WhatsAppFields.accessTokenHelperText')}
      />
      <TextField
        label={t('WhatsAppFields.verifyTokenLabel')}
        value={fieldValue(credentials, 'verify_token')}
        onChange={(event) => onChange({ ...credentials, verify_token: event.target.value })}
        required
        fullWidth
        helperText={t('WhatsAppFields.verifyTokenHelperText')}
        slotProps={{
          input: {
            endAdornment: (
              <Button
                size="small"
                startIcon={<RefreshOutlinedIcon fontSize="small" />}
                onClick={() => onChange({ ...credentials, verify_token: randomToken() })}
              >
                {t('WhatsAppFields.generateButton')}
              </Button>
            ),
          },
        }}
      />
    </Stack>
  )
}
