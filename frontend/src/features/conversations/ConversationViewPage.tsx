import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Box, IconButton, Stack, Tab, Tabs } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useCustomerQuery } from '../customers/api'
import { useRealtime } from '../realtime/context'
import { useConversationQuery } from './api'
import { ConversationSidebar } from './ConversationSidebar'
import { MessageThread } from './MessageThread'
import { ReplyBox } from './ReplyBox'
import { NotesPanel } from './NotesPanel'
import { TransferHistoryPanel } from './TransferHistoryPanel'

export function ConversationViewPage() {
  const { t } = useTranslation('conversationsCore')
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'messages' | 'notes' | 'transfers'>('messages')

  const conversationQuery = useConversationQuery(conversationId)
  const customerQuery = useCustomerQuery(conversationQuery.data?.customer_id)
  const { sendTyping } = useRealtime()

  if (conversationQuery.isPending) {
    return <LoadingState label={t('ConversationViewPage.loadingLabel')} />
  }
  if (conversationQuery.isError) {
    return (
      <ErrorState error={conversationQuery.error} onRetry={() => conversationQuery.refetch()} />
    )
  }

  const conversation = conversationQuery.data

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
        <IconButton
          onClick={() => navigate('/conversations')}
          aria-label={t('ConversationViewPage.backButtonAriaLabel')}
          sx={{ mt: 0.5 }}
        >
          <ArrowBackIcon />
        </IconButton>
        {/* Reuses the same PageHeader (and therefore the same single `h1`)
            every other page in the app renders its title through — this
            page previously hand-rolled a smaller, non-h1 title. */}
        <Box sx={{ flexGrow: 1 }}>
          <PageHeader
            title={customerQuery.data?.full_name ?? t('ConversationViewPage.defaultTitle')}
          />
        </Box>
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        sx={{ flexGrow: 1, minHeight: 0, border: 1, borderColor: 'divider', borderRadius: 2 }}
      >
        {/* minHeight: 0 — same flexbox "automatic minimum size" fix as
            AppLayout.tsx's main region. On xs this Box is a column-flex
            sibling of the sidebar below it (the outer Stack switches to
            flexDirection: 'column'); without this it refuses to shrink
            below its content's natural height (Tabs + MessageThread's own
            minimum + ReplyBox), leaving the sidebar's fixed maxHeight:320
            with no actual room inside the workspace's hard height cap. */}
        <Box
          sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0, minHeight: 0 }}
        >
          <Tabs
            value={tab}
            onChange={(_event, value) => setTab(value)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ borderBottom: 1, borderColor: 'divider' }}
          >
            <Tab label={t('ConversationViewPage.messagesTab')} value="messages" />
            <Tab label={t('ConversationViewPage.internalNotesTab')} value="notes" />
            <Tab label={t('ConversationViewPage.transferHistoryTab')} value="transfers" />
          </Tabs>

          {tab === 'messages' && (
            <>
              <MessageThread conversationId={conversation.id} />
              <ReplyBox
                conversationId={conversation.id}
                onTyping={(isTyping) => sendTyping(conversation.id, isTyping)}
              />
            </>
          )}
          {tab === 'notes' && <NotesPanel conversationId={conversation.id} />}
          {tab === 'transfers' && <TransferHistoryPanel conversationId={conversation.id} />}
        </Box>

        <Box
          sx={{
            borderLeft: { md: 1 },
            borderTop: { xs: 1, md: 0 },
            borderColor: 'divider',
            // The sidebar (Status/Transfer/Release/Queue, etc.) gets its
            // own bounded, independently scrolling box on BOTH mobile and
            // desktop — this used to be `overflowY: 'visible'` /
            // `maxHeight: 'none'` on desktop, which meant the sidebar had
            // no scroll container of its own there at all: a tall
            // sidebar (e.g. many ratings, a long note) would overflow the
            // row's `minHeight: 0` bound and grow the whole page instead,
            // dragging the message list/thread along with it on scroll —
            // exactly the "everything scrolls together" bug this fixes.
            // On mobile the cap is a fixed 320px (it's stacked below the
            // already-scrolling message thread); on desktop it's a
            // sibling in the same row, so it just needs to fill and
            // scroll within that row's own height.
            overflowY: 'auto',
            maxHeight: { xs: 320, md: '100%' },
            minHeight: 0,
          }}
        >
          <ConversationSidebar
            conversation={conversation}
            customerName={customerQuery.data?.full_name ?? t('ConversationViewPage.emptyValue')}
            customerRatingAverage={customerQuery.data?.rating_average ?? null}
            customerRatingCount={customerQuery.data?.rating_count ?? 0}
          />
        </Box>
      </Stack>
    </Box>
  )
}
