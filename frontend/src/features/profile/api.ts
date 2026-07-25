import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'

interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

async function changePassword(payload: ChangePasswordRequest): Promise<void> {
  await apiClient.post('/auth/me/password', payload)
}

/** Self-service password change from the agent's own profile. On success
 * every session (including this one) is revoked server-side — callers
 * must log the user out and send them back to /login. */
export function useChangePasswordMutation() {
  return useMutation({ mutationFn: changePassword })
}
