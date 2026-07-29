import { Alert, Button, Link, Stack, TextField } from '@mui/material'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import { useTranslation } from 'react-i18next'
import { fieldValue, type ChannelFieldsProps } from './types'

function randomToken(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '')
}

/** Facebook Messenger and Instagram.
 *
 * They previously had no form at all — the console offered them as
 * "manual JSON setup", so an operator had to know the exact field names
 * with no validation and no guidance, and a typo produced a channel that
 * saved cleanly and never delivered a message. Both ride the same Graph
 * API surface as WhatsApp and need the same two values. */
export function MetaMessagingFields({ credentials, onChange, channelType }: ChannelFieldsProps) {
  const { t } = useTranslation('channelsFields')
  const isInstagram = channelType === 'instagram'

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        {t('MetaMessagingFields.alertBeforeLink')}{' '}
        <Link href="https://developers.facebook.com/apps" target="_blank" rel="noopener noreferrer">
          {t('MetaMessagingFields.alertLinkText')}
        </Link>{' '}
        {isInstagram
          ? t('MetaMessagingFields.alertAfterLinkInstagram')
          : t('MetaMessagingFields.alertAfterLinkMessenger')}
      </Alert>
      <TextField
        label={t('MetaMessagingFields.accessTokenLabel')}
        type="password"
        value={fieldValue(credentials, 'access_token')}
        onChange={(event) => onChange({ ...credentials, access_token: event.target.value })}
        required
        fullWidth
        helperText={t('MetaMessagingFields.accessTokenHelperText')}
      />
      <TextField
        label={t('MetaMessagingFields.verifyTokenLabel')}
        value={fieldValue(credentials, 'verify_token')}
        onChange={(event) => onChange({ ...credentials, verify_token: event.target.value })}
        fullWidth
        // Invented here, not looked up: it is the value you type into
        // Meta's dashboard, so there is nothing to go and find.
        helperText={t('MetaMessagingFields.verifyTokenHelperText')}
        slotProps={{
          input: {
            endAdornment: (
              <Button
                size="small"
                startIcon={<RefreshOutlinedIcon fontSize="small" />}
                onClick={() => onChange({ ...credentials, verify_token: randomToken() })}
              >
                {t('MetaMessagingFields.generateButton')}
              </Button>
            ),
          },
        }}
      />
    </Stack>
  )
}
