import { useState } from 'react'
import { TextField } from '@mui/material'
import type { ChannelFieldsProps } from './types'

/** Every channel type without a guided form yet (Messenger, Instagram,
 * SMS) — unchanged from the pre-Phase-1 behavior. See
 * channel-integration-spec.md's "priority order" scoping. */
export function GenericJsonFields({ credentials, onChange }: ChannelFieldsProps) {
  const [text, setText] = useState(() => JSON.stringify(credentials, null, 2))
  const [error, setError] = useState<string | null>(null)

  return (
    <TextField
      label="Credentials (JSON)"
      value={text}
      onChange={(event) => {
        setText(event.target.value)
        try {
          onChange(JSON.parse(event.target.value || '{}') as Record<string, unknown>)
          setError(null)
        } catch {
          setError('Enter valid JSON.')
        }
      }}
      fullWidth
      multiline
      minRows={3}
      error={Boolean(error)}
      helperText={error ?? 'Provider-specific credentials as a JSON object'}
    />
  )
}
