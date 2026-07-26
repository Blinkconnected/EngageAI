import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Alert, Button, Divider, Link, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useAllQueuesQuery } from '../queues/api'
import { useCurrentUserQuery } from '../session/api'
import {
  CONVERSATION_KEY,
  CONVERSATIONS_LIST_KEY,
  useReleaseConversationMutation,
  useUpdateConversationMutation,
} from './api'
import { TransferDialog } from './TransferDialog'
import { CONVERSATION_STATUSES, type Conversation } from './types'

export function ConversationSidebar({
  conversation,
  customerName,
}: {
  conversation: Conversation
  customerName: string
}) {
  const { hasPermission } = usePermissions()
  const canTransfer = hasPermission('conversations.transfer')
  const [transferOpen, setTransferOpen] = useState(false)
  const [releaseError, setReleaseError] = useState<string | null>(null)

  const { data: currentUser } = useCurrentUserQuery()
  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateConversationMutation(conversation.id)
  const releaseMutation = useReleaseConversationMutation()
  const queryClient = useQueryClient()

  const myAgentId = agentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)?.id
  // Mirrors the backend's own authorization rule (ConversationService
  // .release()): releasing your own actively-assigned conversation only
  // needs the routine conversations.release permission, but releasing a
  // colleague's is a reassignment, which requires the supervisory
  // conversations.transfer permission (same gate as the Transfer button
  // above) — otherwise any Agent-role principal (conversations.release is
  // granted to every Agent by default) could re-home someone else's
  // conversation to themselves via Release-then-Pick.
  const isAssignedToSelf =
    conversation.assigned_agent_id != null && conversation.assigned_agent_id === myAgentId
  const canRelease = hasPermission('conversations.release') && (canTransfer || isAssignedToSelf)

  function handleRelease() {
    setReleaseError(null)
    releaseMutation.mutate(conversation.id, {
      onError: (error) => {
        setReleaseError(extractErrorMessage(error, 'Could not release this conversation.'))
        // A 409 means the conversation's assignment already changed
        // server-side (e.g. transferred away) since this sidebar last
        // loaded it — refetch immediately rather than leaving the stale
        // "assigned to" state on screen.
        if (isAxiosError(error) && error.response?.status === 409) {
          void queryClient.invalidateQueries({ queryKey: CONVERSATION_KEY(conversation.id) })
          void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
        }
      },
    })
  }

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)
  const assignedAgent = agentsQuery.data?.find((a) => a.id === conversation.assigned_agent_id)
  const assignedDepartment = departmentsQuery.data?.find(
    (d) => d.id === conversation.department_id,
  )

  return (
    <Stack spacing={2} sx={{ p: 2, width: { xs: '100%', md: 280 }, flexShrink: 0 }}>
      {releaseError && <Alert severity="error">{releaseError}</Alert>}

      <div>
        <Typography variant="overline" color="text.secondary">
          Customer
        </Typography>
        <Typography variant="subtitle1">
          <Link component={RouterLink} to={`/customers/${conversation.customer_id}`}>
            {customerName}
          </Link>
        </Typography>
      </div>
      <div>
        <Typography variant="overline" color="text.secondary">
          Channel
        </Typography>
        <Typography variant="body2">{channel?.display_name ?? '—'}</Typography>
      </div>

      <Divider />

      <TextField
        select
        label="Status"
        size="small"
        value={conversation.status}
        onChange={(event) =>
          updateMutation.mutate({ status: event.target.value as Conversation['status'] })
        }
      >
        {CONVERSATION_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {status[0].toUpperCase() + status.slice(1)}
          </MenuItem>
        ))}
      </TextField>

      <div>
        <Typography variant="overline" color="text.secondary">
          Assigned to
        </Typography>
        <Typography variant="body2">
          {assignedAgent?.full_name ??
            (assignedDepartment ? `${assignedDepartment.name} (department)` : 'Unassigned')}
        </Typography>
        {/* Reassignment always goes through the Transfer dialog, not a
            free-form dropdown — see TransferDialog.tsx's docstring on why
            (permission gate, history, recipient notification). Hidden
            entirely (not just disabled) for anyone without
            conversations.transfer, matching this feature's RBAC
            requirement rather than only cosmetically discouraging it. */}
        <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
          {canTransfer && (
            <Button size="small" onClick={() => setTransferOpen(true)}>
              Transfer…
            </Button>
          )}
          {/* Only offered once someone actually holds the conversation —
              releasing an already-unassigned one is a no-op the backend
              400s on, not a real action to expose. `canRelease` above
              already folds in the "is this my own conversation, or do I
              hold conversations.transfer" check, so this second
              condition only needs to confirm *something* is assigned. */}
          {canRelease && conversation.assigned_agent_id && (
            <Button
              size="small"
              color="warning"
              disabled={releaseMutation.isPending}
              onClick={handleRelease}
            >
              {releaseMutation.isPending ? 'Releasing…' : 'Release'}
            </Button>
          )}
        </Stack>
      </div>

      <TextField
        select
        label="Queue"
        size="small"
        value={conversation.queue_id ?? ''}
        disabled={queuesQuery.isPending}
        onChange={(event) => updateMutation.mutate({ queue_id: event.target.value || null })}
      >
        <MenuItem value="">No queue</MenuItem>
        {queuesQuery.data?.map((queue) => (
          <MenuItem key={queue.id} value={queue.id}>
            {queue.name}
          </MenuItem>
        ))}
      </TextField>

      {transferOpen && (
        <TransferDialog conversation={conversation} onClose={() => setTransferOpen(false)} />
      )}
    </Stack>
  )
}
