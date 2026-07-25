import { useState } from 'react'
import { Alert, Button, Stack } from '@mui/material'
import NetworkCheckOutlinedIcon from '@mui/icons-material/NetworkCheckOutlined'
import { extractErrorMessage } from '../../shared/api/errors'
import type { TestConnectionResult } from './types'

interface TestConnectionButtonProps {
  onTest: () => Promise<TestConnectionResult>
  disabled?: boolean
}

type State =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'succeeded'; result: TestConnectionResult }
  | { status: 'errored'; error: unknown }

/** Reused across the create wizard (ephemeral, unsaved credentials) and
 * the edit/reconnect view (an already-saved channel) — same button, same
 * result presentation, different callback. See
 * channel-integration-spec.md's "consistent UX across all channels". */
export function TestConnectionButton({ onTest, disabled }: TestConnectionButtonProps) {
  const [state, setState] = useState<State>({ status: 'idle' })

  async function handleClick() {
    setState({ status: 'pending' })
    try {
      const result = await onTest()
      setState({ status: 'succeeded', result })
    } catch (error) {
      setState({ status: 'errored', error })
    }
  }

  return (
    <Stack spacing={1} sx={{ alignItems: 'flex-start' }}>
      <Button
        variant="outlined"
        size="small"
        startIcon={<NetworkCheckOutlinedIcon fontSize="small" />}
        onClick={handleClick}
        disabled={disabled || state.status === 'pending'}
      >
        {state.status === 'pending' ? 'Testing…' : 'Test Connection'}
      </Button>
      {state.status === 'succeeded' && (
        <Alert severity={state.result.healthy ? 'success' : 'error'} sx={{ width: '100%' }}>
          {state.result.healthy ? 'Connected successfully.' : (state.result.detail ?? 'Connection failed.')}
        </Alert>
      )}
      {state.status === 'errored' && (
        <Alert severity="error" sx={{ width: '100%' }}>
          {extractErrorMessage(state.error, 'Could not test the connection.')}
        </Alert>
      )}
    </Stack>
  )
}
