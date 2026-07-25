import { Stack, TextField } from '@mui/material'
import { fieldValue, type ChannelFieldsProps } from './types'

export function TelegramFields({ credentials, onChange }: ChannelFieldsProps) {
  return (
    <Stack spacing={2}>
      <TextField
        label="Bot token"
        type="password"
        value={fieldValue(credentials, 'bot_token')}
        onChange={(event) => onChange({ ...credentials, bot_token: event.target.value })}
        required
        fullWidth
        helperText="From @BotFather — the token printed after /newbot (or /token for an existing bot)"
      />
    </Stack>
  )
}
