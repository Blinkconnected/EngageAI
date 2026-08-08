import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Skeleton, Stack, Typography, useMediaQuery } from '@mui/material'
import type { Theme } from '@mui/material/styles'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useNow } from '../../shared/hooks/useNow'
import { useAllChannelsQuery } from '../channels/api'
import { ConversationRow } from './ConversationRow'
import { ConversationViewPage } from './ConversationViewPage'
import { OperationalSummary } from './OperationalSummary'
import { WorkQueues } from './WorkQueues'
import { useConversationsQuery, usePickConversationMutation } from './api'
import { useWorkloadQuery } from './inboxApi'
import { WORK_QUEUES, type InboxView } from './inboxTypes'

/** How often the list re-reads itself.
 *
 * The Inbox is a live operations screen: a conversation that breached two
 * minutes ago and is not on it yet is a conversation nobody is going to.
 * Matched to the workload strip so the counts and the rows never disagree
 * about the same moment for long.
 */
const REFETCH_MS = 30_000

/** Wide enough for a customer name, a state and a duration on one line;
 * narrow enough that the conversation beside it still gets the room a
 * conversation needs. */
const LIST_PANE_WIDTH = 380

const DEFAULT_VIEW: InboxView = 'needs_attention'

function isView(value: string | null): value is InboxView {
  return value !== null && (WORK_QUEUES as string[]).includes(value)
}

/** The agent's operational workspace: the list and the conversation, side
 * by side.
 *
 * Opening a conversation used to replace this screen entirely. An agent
 * working a queue therefore did list → conversation → Back → list →
 * conversation, losing their place in the list every time and paying a
 * full page load for each one. Both panes are now on screen at once, the
 * list keeps its scroll position and its selection, and the URL still
 * carries the open conversation so a link to one still works.
 *
 * The list itself still answers the questions in the order somebody asks
 * them at 9am — what does my day look like, what needs attention, what
 * do I open — but in a fifth of the vertical space, because the answers
 * now sit beside the work instead of on top of it.
 */
export function InboxWorkspace() {
  const { t } = useTranslation('conversationsCore')
  const navigate = useNavigate()
  const { conversationId } = useParams<{ conversationId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { hasPermission } = usePermissions()
  const now = useNow()

  // One breakpoint decides the whole layout: two panes, or one at a time.
  // Below it there is not room for a list and a conversation without
  // making both unusable, so selecting a row becomes a real navigation
  // and the conversation gets a back button.
  const isWide = useMediaQuery((theme: Theme) => theme.breakpoints.up('md'))

  const viewParam = searchParams.get('view')
  const view: InboxView = isView(viewParam) ? viewParam : DEFAULT_VIEW

  const workloadQuery = useWorkloadQuery()
  const conversationsQuery = useConversationsQuery(
    { page: 1, page_size: 50, view },
    { refetchInterval: REFETCH_MS },
  )
  const channelsQuery = useAllChannelsQuery()
  const pickMutation = usePickConversationMutation()
  const [pickError, setPickError] = useState<string | null>(null)

  const channelById = useMemo(() => {
    const map = new Map<string, string>()
    for (const channel of channelsQuery.data ?? []) map.set(channel.id, channel.channel_type)
    return map
  }, [channelsQuery.data])

  const selectView = useCallback(
    (next: InboxView) => {
      // Replace rather than push: moving between queues is changing what you
      // are looking at, not navigating somewhere new, and an agent who tried
      // four queues should not have to press Back four times to leave.
      setSearchParams(next === DEFAULT_VIEW ? {} : { view: next }, { replace: true })
    },
    [setSearchParams],
  )

  const openConversation = useCallback(
    (id: string) => {
      // The queue survives the click. Opening a conversation from
      // *Breached* and coming back to *Needs attention* would lose the
      // desk the agent chose to sit at.
      const query = searchParams.toString()
      navigate(`/conversations/${id}${query ? `?${query}` : ''}`, { replace: isWide })
    },
    [navigate, searchParams, isWide],
  )

  const closeConversation = useCallback(() => {
    const query = searchParams.toString()
    navigate(`/conversations${query ? `?${query}` : ''}`)
  }, [navigate, searchParams])

  const handlePick = useCallback(
    (id: string) => {
      setPickError(null)
      pickMutation.mutate(id, {
        onError: () => setPickError(t('ConversationSidebar.pickErrorFallback')),
      })
    },
    [pickMutation, t],
  )

  const rows = conversationsQuery.data?.items ?? []
  const loading = conversationsQuery.isPending
  const canPick = hasPermission('conversations.pick')

  const listPane = (
    <Stack
      component="section"
      aria-label={t(`Inbox.view.${view}`)}
      sx={{
        width: isWide ? LIST_PANE_WIDTH : '100%',
        flexShrink: 0,
        minHeight: 0,
        borderInlineEnd: isWide ? 1 : 0,
        borderColor: 'divider',
        bgcolor: 'background.paper',
      }}
    >
      {/* Everything above the rows, kept to two lines. This screen's
          worst habit was spending the top third of itself on chrome. */}
      <Box sx={{ px: 2, pt: 2, pb: 1, flexShrink: 0 }}>
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: 'baseline', justifyContent: 'space-between' }}
        >
          <Typography variant="h6" component="h1" sx={{ fontWeight: 700 }}>
            {t('Inbox.title')}
          </Typography>
          <OperationalSummary workload={workloadQuery.data} loading={workloadQuery.isPending} />
        </Stack>
      </Box>

      <Box sx={{ px: 2, pb: 1, flexShrink: 0 }}>
        <WorkQueues selected={view} workload={workloadQuery.data} onSelect={selectView} />
      </Box>

      {/* What the queue means, said once, where the rows begin. */}
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{
          px: 2,
          pb: 1,
          flexShrink: 0,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        {t(`Inbox.viewMeaning.${view}`)}
      </Typography>

      {pickError && (
        <Alert severity="error" sx={{ m: 1 }} onClose={() => setPickError(null)}>
          {pickError}
        </Alert>
      )}

      {/* The rows own the rest of the pane and scroll inside it. The page
          itself never scrolls — the two panes scroll independently, which
          is what lets the list stay put while a conversation is read. */}
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto' }}>
        {conversationsQuery.isError ? (
          <Box sx={{ p: 2 }}>
            <Alert
              severity="error"
              action={
                <Button
                  color="inherit"
                  size="small"
                  onClick={() => void conversationsQuery.refetch()}
                >
                  {t('Inbox.retry')}
                </Button>
              }
            >
              {t('Inbox.loadFailed')}
            </Alert>
          </Box>
        ) : loading ? (
          <Stack sx={{ p: 2 }} spacing={2} data-testid="inbox-skeleton">
            {Array.from({ length: 5 }, (_, index) => (
              <Box key={index}>
                <Skeleton width="30%" />
                <Skeleton width="55%" />
              </Box>
            ))}
          </Stack>
        ) : rows.length === 0 ? (
          // Named for the queue, because "nothing needs attention" and
          // "nothing has breached" are different pieces of good news, and a
          // generic empty state throws away which one an agent just earned.
          <EmptyState
            title={t(`Inbox.empty.${view}`, { defaultValue: t('Inbox.empty.generic') })}
            description={t('Inbox.emptyDescription')}
          />
        ) : (
          <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0 }}>
            {rows.map((conversation) => (
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                channelType={channelById.get(conversation.channel_config_id) ?? null}
                onOpen={openConversation}
                selected={conversation.id === conversationId}
                onPick={canPick ? handlePick : undefined}
                pickPending={pickMutation.isPending && pickMutation.variables === conversation.id}
                now={now}
              />
            ))}
          </Box>
        )}
      </Box>
    </Stack>
  )

  // Narrow screens are one thing at a time: a 380px list and a
  // conversation side by side on a phone gives you neither.
  if (!isWide) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        {conversationId ? (
          <ConversationViewPage conversationId={conversationId} onBack={closeConversation} />
        ) : (
          listPane
        )}
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', height: '100%', minHeight: 0, overflow: 'hidden' }}>
      {listPane}
      <Box sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {conversationId ? (
          <ConversationViewPage conversationId={conversationId} />
        ) : (
          // Not a blank pane: the empty half of a two-pane workspace is
          // the one place there is room to say what the screen is for.
          <Box
            sx={{
              flexGrow: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              p: 4,
            }}
          >
            <EmptyState
              title={t('Inbox.noSelectionTitle')}
              description={t('Inbox.noSelectionDescription')}
            />
          </Box>
        )}
      </Box>
    </Box>
  )
}
