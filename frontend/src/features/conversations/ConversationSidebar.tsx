import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Button,
  Chip,
  Divider,
  Link,
  MenuItem,
  Rating,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useAllQueuesQuery } from '../queues/api'
import { useCurrentUserQuery } from '../session/api'
import { useSummarizeConversationMutation } from './aiApi'
import {
  CONVERSATION_KEY,
  CONVERSATIONS_LIST_KEY,
  usePickConversationMutation,
  useRequestAutopilotMutation,
  useReleaseConversationMutation,
  useUpdateConversationMutation,
} from './api'
import { TransferDialog } from './TransferDialog'
import { CONVERSATION_STATUSES, type Conversation, type ConversationStatus } from './types'

// Maps each status to the i18n key holding its dropdown label — the label
// itself can't live in this module-scope map since translation requires
// the `t` function, which is only available inside the component.
const STATUS_OPTION_KEY: Record<ConversationStatus, string> = {
  open: 'statusOpen',
  pending: 'statusPending',
  resolved: 'statusResolved',
  closed: 'statusClosed',
}

export function ConversationSidebar({
  conversation,
  customerName,
  customerRatingAverage,
  customerRatingCount,
}: {
  conversation: Conversation
  customerName: string
  customerRatingAverage: number | null
  customerRatingCount: number
}) {
  const { t } = useTranslation('conversationsCore')
  const { hasPermission } = usePermissions()
  const canTransfer = hasPermission('conversations.transfer')
  const canPick = hasPermission('conversations.pick')
  // The Autopilot request endpoint rides conversations.manage — an
  // agent who may reply may also ask AI to reply for them.
  const canManage = hasPermission('conversations.manage')
  const [transferOpen, setTransferOpen] = useState(false)
  const [releaseError, setReleaseError] = useState<string | null>(null)
  const [pickError, setPickError] = useState<string | null>(null)

  const { data: currentUser } = useCurrentUserQuery()
  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateConversationMutation(conversation.id)
  const releaseMutation = useReleaseConversationMutation()
  const pickMutation = usePickConversationMutation()
  const autopilotMutation = useRequestAutopilotMutation()
  const summaryMutation = useSummarizeConversationMutation()
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
        setReleaseError(extractErrorMessage(error, t('ConversationSidebar.releaseErrorFallback')))
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

  // The only ownership action reachable from this page before this fix
  // was Transfer/Release, both of which require an existing assignment —
  // an agent arriving here from an unassigned-conversation notification
  // (SLA breach, autopilot handoff) had no way to actually claim it
  // without going back to the Inbox and hunting the row. Mirrors
  // InboxPage.tsx's own handlePick.
  function handlePick() {
    setPickError(null)
    pickMutation.mutate(conversation.id, {
      onError: (error) => {
        setPickError(extractErrorMessage(error, t('ConversationSidebar.pickErrorFallback')))
        if (isAxiosError(error) && error.response?.status === 409) {
          void queryClient.invalidateQueries({ queryKey: CONVERSATION_KEY(conversation.id) })
          void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
        }
      },
    })
  }

  function handleRequestAutopilot() {
    setPickError(null)
    autopilotMutation.mutate(conversation.id, {
      onError: (error) => {
        setPickError(
          extractErrorMessage(error, t('ConversationSidebar.autopilotRequestErrorFallback')),
        )
      },
    })
  }

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)
  const assignedAgent = agentsQuery.data?.find((a) => a.id === conversation.assigned_agent_id)
  const assignedDepartment = departmentsQuery.data?.find((d) => d.id === conversation.department_id)

  return (
    <Stack spacing={2} sx={{ p: 2, width: { xs: '100%', md: 280 }, flexShrink: 0 }}>
      {releaseError && <Alert severity="error">{releaseError}</Alert>}
      {pickError && <Alert severity="error">{pickError}</Alert>}
      {updateMutation.isError && (
        <Alert severity="error" onClose={() => updateMutation.reset()}>
          {extractErrorMessage(updateMutation.error, t('ConversationSidebar.updateErrorFallback'))}
        </Alert>
      )}

      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.customerLabel')}
        </Typography>
        {/* `component="p"` — MUI's default subtitle1 mapping is `<h6>`,
            which (now that ConversationViewPage renders a real `<h1>`
            via PageHeader) would otherwise skip straight from h1 to h6. */}
        <Typography variant="subtitle1" component="p">
          <Link component={RouterLink} to={`/customers/${conversation.customer_id}`}>
            {customerName}
          </Link>
        </Typography>
        {customerRatingCount > 0 && (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Rating value={customerRatingAverage} precision={0.5} readOnly size="small" />
            <Typography variant="caption" color="text.secondary">
              {t('ConversationSidebar.customerRatingCount', { count: customerRatingCount })}
            </Typography>
          </Stack>
        )}
      </div>
      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.channelLabel')}
        </Typography>
        <Typography variant="body2">
          {channel?.display_name ?? t('ConversationSidebar.emptyValue')}
        </Typography>
      </div>

      {hasPermission('ai.use') && (
        <div>
          <Typography variant="overline" color="text.secondary">
            {t('ConversationSidebar.aiSummaryLabel')}
          </Typography>
          {summaryMutation.isError && (
            <Alert
              severity="error"
              sx={{ mt: 0.5, mb: 0.5 }}
              onClose={() => summaryMutation.reset()}
            >
              {extractErrorMessage(
                summaryMutation.error,
                t('ConversationSidebar.summarizeErrorFallback'),
              )}
            </Alert>
          )}
          {summaryMutation.data ? (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {summaryMutation.data}
            </Typography>
          ) : (
            <Button
              size="small"
              onClick={() => summaryMutation.mutate(conversation.id)}
              disabled={summaryMutation.isPending}
              sx={{ px: 0 }}
            >
              {summaryMutation.isPending
                ? t('ConversationSidebar.summarizingButton')
                : t('ConversationSidebar.generateSummaryButton')}
            </Button>
          )}
        </div>
      )}

      <Divider />

      <TextField
        select
        label={t('ConversationSidebar.statusLabel')}
        size="small"
        value={conversation.status}
        onChange={(event) =>
          updateMutation.mutate({ status: event.target.value as Conversation['status'] })
        }
      >
        {CONVERSATION_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {t(`ConversationSidebar.${STATUS_OPTION_KEY[status]}`)}
          </MenuItem>
        ))}
      </TextField>

      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.assignedToLabel')}
        </Typography>
        {conversation.autopilot_active ? (
          <div>
            <Chip label={t('ConversationSidebar.autopilotActiveLabel')} size="small" color="info" />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {t('ConversationSidebar.autopilotActiveHelperText')}
            </Typography>
          </div>
        ) : (
          <Typography variant="body2">
            {assignedAgent?.full_name ??
              (assignedDepartment
                ? t('ConversationSidebar.departmentSuffixLabel', {
                    departmentName: assignedDepartment.name,
                  })
                : t('ConversationSidebar.unassignedValue'))}
          </Typography>
        )}
        {/* Reassignment always goes through the Transfer dialog, not a
            free-form dropdown — see TransferDialog.tsx's docstring on why
            (permission gate, history, recipient notification). Hidden
            entirely (not just disabled) for anyone without
            conversations.transfer, matching this feature's RBAC
            requirement rather than only cosmetically discouraging it. */}
        <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
          {/* Only offered when there is genuinely no one holding the
              conversation yet (and it isn't Autopilot's) — once someone
              does, claiming it is a reassignment and goes through
              Transfer instead, not a second Pick. */}
          {canPick && !conversation.assigned_agent_id && !conversation.autopilot_active && (
            <Button
              size="small"
              variant="contained"
              disabled={pickMutation.isPending}
              onClick={handlePick}
            >
              {pickMutation.isPending
                ? t('ConversationSidebar.pickingButton')
                : t('ConversationSidebar.pickButton')}
            </Button>
          )}
          {/* "Ask AI to reply" — the On Agent Request activation mode.
              Offered only while a human still holds the conversation:
              once Autopilot has it, it keeps answering on its own and the
              relevant action becomes picking it back up. A 409 (the mode
              is off company-wide) surfaces through the same error banner
              as every other action here. */}
          {canManage && !conversation.autopilot_active && (
            <Button
              size="small"
              startIcon={<SmartToyOutlinedIcon />}
              disabled={autopilotMutation.isPending}
              onClick={handleRequestAutopilot}
            >
              {autopilotMutation.isPending
                ? t('ConversationSidebar.autopilotRequestingButton')
                : t('ConversationSidebar.autopilotRequestButton')}
            </Button>
          )}
          {canTransfer && (
            <Button size="small" onClick={() => setTransferOpen(true)}>
              {t('ConversationSidebar.transferButton')}
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
              {releaseMutation.isPending
                ? t('ConversationSidebar.releasingButton')
                : t('ConversationSidebar.releaseButton')}
            </Button>
          )}
        </Stack>
      </div>

      <TextField
        select
        label={t('ConversationSidebar.queueLabel')}
        size="small"
        value={conversation.queue_id ?? ''}
        disabled={queuesQuery.isPending}
        onChange={(event) => updateMutation.mutate({ queue_id: event.target.value || null })}
      >
        <MenuItem value="">{t('ConversationSidebar.noQueueOption')}</MenuItem>
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
