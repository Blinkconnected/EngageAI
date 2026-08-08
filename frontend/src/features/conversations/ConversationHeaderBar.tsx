import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Link,
  Rating,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlineOutlined'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useNow } from '../../shared/hooks/useNow'
import { formatElapsed } from '../../shared/utils/formatElapsed'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllQueuesQuery } from '../queues/api'
import { useCurrentUserQuery } from '../session/api'
import { AutopilotBadge, ChannelIcon, SlaIndicator } from './ConversationCells'
import { TransferDialog } from './TransferDialog'
import {
  CONVERSATION_KEY,
  CONVERSATIONS_LIST_KEY,
  usePickConversationMutation,
  useReleaseConversationMutation,
  useRequestAutopilotMutation,
  useStopAutopilotMutation,
} from './api'
import type { Conversation } from './types'

/** One fact and its label, in the strip. */
function Fact({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <Box sx={{ minWidth: 0 }} title={title}>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: 'block', lineHeight: 1.2 }}
      >
        {label}
      </Typography>
      <Typography
        variant="body2"
        sx={{ fontWeight: 600, lineHeight: 1.3, fontVariantNumeric: 'tabular-nums' }}
        noWrap
      >
        {value}
      </Typography>
    </Box>
  )
}

/**
 * Everything an agent needs before typing a word, without opening
 * anything.
 *
 * All of this used to live behind a `⋮` menu that opened a drawer: who
 * the customer is, what the conversation is waiting on, whether it has
 * breached, who owns it, how long it has been like that — and *Pick up*,
 * the single most common action on the screen, three clicks deep.
 *
 * The times are the reason this is a strip and not a summary sentence.
 * "Waiting 4m" and "Waiting 4h" call for completely different behaviour,
 * and an agent reads them before deciding whether to reply now or
 * escalate. They tick (see `useNow`) because a duration rendered once
 * and left alone is not stale, it is wrong.
 */
export function ConversationHeaderBar({
  conversation,
  customerName,
  customerRatingAverage,
  customerRatingCount,
  onOpenDetails,
  onBack,
}: {
  conversation: Conversation
  customerName: string | null
  customerRatingAverage: number | null
  customerRatingCount: number
  onOpenDetails: () => void
  /** Only supplied on narrow screens, where the list and the conversation
   * are separate views rather than two panes. */
  onBack?: () => void
}) {
  const { t } = useTranslation('conversationsCore')
  const { hasPermission } = usePermissions()
  const queryClient = useQueryClient()
  const now = useNow()
  const [actionError, setActionError] = useState<string | null>(null)
  const [transferOpen, setTransferOpen] = useState(false)

  const { data: currentUser } = useCurrentUserQuery()
  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const queuesQuery = useAllQueuesQuery()

  const pickMutation = usePickConversationMutation()
  const releaseMutation = useReleaseConversationMutation()
  const autopilotMutation = useRequestAutopilotMutation()
  const stopAutopilotMutation = useStopAutopilotMutation()

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)
  const queue = queuesQuery.data?.find((q) => q.id === conversation.queue_id)
  const myAgentId = agentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)?.id

  const canPick = hasPermission('conversations.pick')
  const canTransfer = hasPermission('conversations.transfer')
  const canManage = hasPermission('conversations.manage')
  // Mirrors the backend rule (ConversationService.release): releasing your
  // own needs conversations.release, releasing a colleague's is a
  // reassignment and needs the supervisory permission too.
  const isAssignedToSelf =
    conversation.assigned_agent_id != null && conversation.assigned_agent_id === myAgentId
  const canRelease = hasPermission('conversations.release') && (canTransfer || isAssignedToSelf)

  const isUnclaimed = !conversation.assigned_agent_id && !conversation.autopilot_active

  function runAction(
    mutate: (id: string, options: { onError: (error: unknown) => void }) => void,
    fallback: string,
  ) {
    setActionError(null)
    mutate(conversation.id, {
      onError: (error: unknown) => {
        setActionError(extractErrorMessage(error, fallback))
        // A 409 means somebody else changed the assignment while this was
        // on screen — reload rather than leave a stale owner showing.
        if (isAxiosError(error) && error.response?.status === 409) {
          void queryClient.invalidateQueries({ queryKey: CONVERSATION_KEY(conversation.id) })
          void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
        }
      },
    })
  }

  const waiting = formatElapsed(conversation.owner_since, now)
  const lastMessage = formatElapsed(conversation.last_message_at, now)
  const opened = formatElapsed(conversation.created_at, now)
  const dash = t('ConversationHeaderBar.emptyValue')

  return (
    <Box
      component="header"
      sx={{ flexShrink: 0, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}
    >
      {/* WHO, and what can be done about it. */}
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: 'center', px: 2, pt: 1.5, pb: 1, flexWrap: 'wrap', rowGap: 1 }}
      >
        {onBack && (
          <IconButton
            onClick={onBack}
            size="small"
            aria-label={t('ConversationViewPage.backButtonAriaLabel')}
          >
            <ArrowBackIcon />
          </IconButton>
        )}

        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', minWidth: 0 }}>
            {/* `component="h2"`: the workspace's single `h1` is the Inbox
                heading, and the open conversation is a section of it. */}
            <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 700 }} noWrap>
              {customerName ? (
                <Link component={RouterLink} to={`/customers/${conversation.customer_id}`}>
                  {customerName}
                </Link>
              ) : (
                t('ConversationViewPage.defaultTitle')
              )}
            </Typography>
            {/* No Tooltip wrapper — ChannelIcon carries its own, and
                nesting two puts a second labelled element in the tree. */}
            {channel && <ChannelIcon channelType={channel.channel_type} />}
            {customerRatingCount > 0 && (
              <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                <Rating value={customerRatingAverage} precision={0.5} readOnly size="small" />
                <Typography variant="caption" color="text.secondary">
                  ({customerRatingCount})
                </Typography>
              </Stack>
            )}
          </Stack>
        </Box>

        {/* The actions, in the open, in the order they get used. Pick up
            is `contained` and first because on an unclaimed conversation
            it is the only thing anybody does — it spent this screen's
            whole life buried in a drawer behind a `⋮`. */}
        {canPick && isUnclaimed && (
          <Button
            variant="contained"
            size="small"
            disabled={pickMutation.isPending}
            onClick={() =>
              runAction(pickMutation.mutate, t('ConversationSidebar.pickErrorFallback'))
            }
          >
            {pickMutation.isPending
              ? t('ConversationSidebar.pickingButton')
              : t('ConversationSidebar.pickButton')}
          </Button>
        )}
        {canManage && conversation.autopilot_active && (
          <Button
            variant="contained"
            size="small"
            startIcon={<PersonOutlineIcon />}
            disabled={stopAutopilotMutation.isPending}
            onClick={() =>
              runAction(
                stopAutopilotMutation.mutate,
                t('ConversationSidebar.autopilotTakeOverErrorFallback'),
              )
            }
          >
            {stopAutopilotMutation.isPending
              ? t('ConversationSidebar.autopilotTakingOverButton')
              : t('ConversationSidebar.autopilotTakeOverButton')}
          </Button>
        )}
        {canManage && !conversation.autopilot_active && (
          <Button
            size="small"
            startIcon={<SmartToyOutlinedIcon />}
            disabled={autopilotMutation.isPending}
            onClick={() =>
              runAction(
                autopilotMutation.mutate,
                t('ConversationSidebar.autopilotRequestErrorFallback'),
              )
            }
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
        {canRelease && conversation.assigned_agent_id && (
          <Button
            size="small"
            color="warning"
            disabled={releaseMutation.isPending}
            onClick={() =>
              runAction(releaseMutation.mutate, t('ConversationSidebar.releaseErrorFallback'))
            }
          >
            {releaseMutation.isPending
              ? t('ConversationSidebar.releasingButton')
              : t('ConversationSidebar.releaseButton')}
          </Button>
        )}
        <Tooltip title={t('ConversationViewPage.conversationDetails')}>
          <IconButton
            onClick={onOpenDetails}
            size="small"
            aria-label={t('ConversationViewPage.conversationDetails')}
          >
            <InfoOutlinedIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      {actionError && (
        <Alert severity="error" sx={{ mx: 2, mb: 1 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      {/* WHAT STATE, and FOR HOW LONG — the strip this screen was missing.
          Scrolls sideways rather than wrapping into a second block: the
          composer and the thread must keep their height on a laptop. */}
      <Stack
        direction="row"
        spacing={3}
        component="section"
        aria-label={t('ConversationHeaderBar.statusStripAria')}
        sx={{
          px: 2,
          pb: 1.25,
          alignItems: 'center',
          overflowX: 'auto',
          '&::-webkit-scrollbar': { height: 4 },
        }}
      >
        <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', flexShrink: 0 }}>
          <Chip size="small" variant="outlined" label={conversation.state_text} />
          <SlaIndicator conversation={conversation} />
          {conversation.autopilot_active && <AutopilotBadge />}
          {conversation.priority !== 'normal' && (
            <Chip
              size="small"
              variant="outlined"
              color={conversation.priority === 'urgent' ? 'error' : 'default'}
              label={t(`InboxPage.priority.${conversation.priority}`)}
            />
          )}
          {conversation.unread_count > 0 && (
            <Chip size="small" color="primary" label={conversation.unread_count} />
          )}
        </Stack>

        <Fact
          label={t('ConversationHeaderBar.owner')}
          value={conversation.owner_label || t('Inbox.nobodyOwns')}
        />
        {/* The three durations, in the order the questions get asked:
            how long has it been like this, when did they last speak,
            and how old is the whole thing. */}
        <Fact
          label={t('ConversationHeaderBar.waiting')}
          value={waiting ?? dash}
          title={conversation.owner_since ?? undefined}
        />
        <Fact
          label={t('ConversationHeaderBar.lastMessage')}
          value={lastMessage ? t('ConversationHeaderBar.ago', { duration: lastMessage }) : dash}
          title={conversation.last_message_at ?? undefined}
        />
        <Fact
          label={t('ConversationHeaderBar.opened')}
          value={opened ? t('ConversationHeaderBar.ago', { duration: opened }) : dash}
          title={conversation.created_at}
        />
        {/* Only once it has happened: "First reply —" on a conversation
            nobody has answered reads as a missing value rather than as
            the thing an agent is about to fix. */}
        {conversation.first_response_at && (
          <Fact
            label={t('ConversationHeaderBar.firstReply')}
            value={t('ConversationHeaderBar.ago', {
              duration: formatElapsed(conversation.first_response_at, now),
            })}
            title={conversation.first_response_at}
          />
        )}
        <Fact label={t('ConversationHeaderBar.queue')} value={queue?.name ?? dash} />
      </Stack>

      {transferOpen && (
        <TransferDialog conversation={conversation} onClose={() => setTransferOpen(false)} />
      )}
    </Box>
  )
}
