import { useCallback, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, Skeleton, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { PageHeader } from '../../shared/components/PageHeader'
import { useAllChannelsQuery } from '../channels/api'
import { ConversationRow } from './ConversationRow'
import { OperationalSummary } from './OperationalSummary'
import { WorkQueues } from './WorkQueues'
import { useConversationsQuery } from './api'
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

const DEFAULT_VIEW: InboxView = 'needs_attention'

function isView(value: string | null): value is InboxView {
  return value !== null && (WORK_QUEUES as string[]).includes(value)
}

/** The agent's operational workspace.
 *
 * Three layers, in the order of the questions somebody actually asks at 9am:
 *
 *   1. What does my day look like?      → the operational summary
 *   2. What requires my attention?      → the work queues
 *   3. What should I work on next?      → the conversations
 *
 * The order is not negotiable, because it is the order of the questions. The
 * screen this replaces collapsed all three into a table and the instruction
 * "figure it out".
 *
 * Selecting a queue is meant to feel like changing what you are doing, not
 * like editing a filter — so the queue lives in the URL, the heading changes
 * with it, and the list below is only ever the work of that queue.
 */
export function InboxWorkspace() {
  const { t } = useTranslation('conversationsCore')
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const viewParam = searchParams.get('view')
  const view: InboxView = isView(viewParam) ? viewParam : DEFAULT_VIEW

  const workloadQuery = useWorkloadQuery()
  const conversationsQuery = useConversationsQuery(
    { page: 1, page_size: 50, view },
    { refetchInterval: REFETCH_MS },
  )
  const channelsQuery = useAllChannelsQuery()

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

  const openConversation = useCallback((id: string) => navigate(`/conversations/${id}`), [navigate])

  const rows = conversationsQuery.data?.items ?? []
  const loading = conversationsQuery.isPending

  return (
    <>
      <PageHeader title={t('Inbox.title')} description={t('Inbox.description')} />

      {/* 1. What does my day look like? */}
      <OperationalSummary workload={workloadQuery.data} loading={workloadQuery.isPending} />

      {/* 2. What requires my attention? */}
      <WorkQueues selected={view} workload={workloadQuery.data} onSelect={selectView} />

      {/* 3. What should I work on next? */}
      <Box
        component="section"
        aria-label={t(`Inbox.view.${view}`)}
        sx={{ border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}
      >
        <Stack
          direction="row"
          spacing={1}
          sx={{
            px: 2,
            py: 1,
            alignItems: 'baseline',
            borderBottom: 1,
            borderColor: 'divider',
            bgcolor: 'background.default',
          }}
        >
          {/* The heading names the *work*, not the filter. Entering a queue
              should feel like sitting at a different desk. */}
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {t(`Inbox.view.${view}`)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t(`Inbox.viewMeaning.${view}`)}
          </Typography>
        </Stack>

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
              />
            ))}
          </Box>
        )}
      </Box>
    </>
  )
}
