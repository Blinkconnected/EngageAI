import { Button, Stack, TextField } from '@mui/material'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import { fieldValue, type ChannelFieldsProps } from './types'

function randomToken(): string {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, '')
}

export function WhatsAppFields({ credentials, onChange }: ChannelFieldsProps) {
  return (
    <Stack spacing={2}>
      <TextField
        label="Phone number ID"
        value={fieldValue(credentials, 'phone_number_id')}
        onChange={(event) => onChange({ ...credentials, phone_number_id: event.target.value })}
        required
        fullWidth
        helperText="From Meta's WhatsApp Business App Dashboard"
      />
      <TextField
        label="Access token"
        type="password"
        value={fieldValue(credentials, 'access_token')}
        onChange={(event) => onChange({ ...credentials, access_token: event.target.value })}
        required
        fullWidth
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
