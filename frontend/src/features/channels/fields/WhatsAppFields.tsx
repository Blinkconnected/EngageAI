import { Alert, Button, Link, Stack, TextField } from '@mui/material'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import { fieldValue, type ChannelFieldsProps } from './types'

function randomToken(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '')
}

export function WhatsAppFields({ credentials, onChange }: ChannelFieldsProps) {
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Both values come from{' '}
        <Link
          href="https://developers.facebook.com/apps"
          target="_blank"
          rel="noopener noreferrer"
        >
          Meta for Developers
        </Link>{' '}
        → your app → WhatsApp → API Setup. Use a permanent System User token, not the temporary
        one shown by default (it expires in 24 hours).
      </Alert>
      <TextField
        label="Phone number ID"
        value={fieldValue(credentials, 'phone_number_id')}
        onChange={(event) => onChange({ ...credentials, phone_number_id: event.target.value })}
        required
        fullWidth
        placeholder="109876543212345"
        helperText="From Meta's WhatsApp Business App Dashboard"
      />
      <TextField
        label="Access token"
        type="password"
        value={fieldValue(credentials, 'access_token')}
        onChange={(event) => onChange({ ...credentials, access_token: event.target.value })}
        required
        fullWidth
        placeholder="EAAG...permanent-system-user-token"
        helperText="A permanent (System User) access token, not a short-lived one"
      />
      <TextField
        label="Verify token"
        value={fieldValue(credentials, 'verify_token')}
        onChange={(event) => onChange({ ...credentials, verify_token: event.target.value })}
        required
        fullWidth
        helperText="You'll enter this same value in Meta's dashboard"
        slotProps={{
          input: {
            endAdornment: (
              <Button
                size="small"
                startIcon={<RefreshOutlinedIcon fontSize="small" />}
                onClick={() => onChange({ ...credentials, verify_token: randomToken() })}
              >
                Generate
              </Button>
            ),
          },
        }}
      />
    </Stack>
  )
}
