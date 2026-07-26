import { Alert, Link, Stack, TextField } from '@mui/material'
import { fieldValue, type ChannelFieldsProps } from './types'

export function TelegramFields({ credentials, onChange }: ChannelFieldsProps) {
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Don't have a bot yet? Message{' '}
        <Link href="https://t.me/botfather" target="_blank" rel="noopener noreferrer">
          @BotFather
        </Link>{' '}
        on Telegram, send <code>/newbot</code>, and follow the prompts — it replies with the
        token below. No webhook setup needed afterward; BlinkEngage registers it automatically.
      </Alert>
      <TextField
        label="Bot token"
        type="password"
        value={fieldValue(credentials, 'bot_token')}
        onChange={(event) => onChange({ ...credentials, bot_token: event.target.value })}
        required
        fullWidth
        placeholder="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        helperText="From @BotFather — the token printed after /newbot (or /token for an existing bot)"
      />
    </Stack>
  )
}
