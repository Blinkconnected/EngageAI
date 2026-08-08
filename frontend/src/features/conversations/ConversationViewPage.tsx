import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Box, Drawer, IconButton, Stack, Tab, Tabs, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useCustomerQuery } from '../customers/api'
import { useRealtime } from '../realtime/context'
import { useConversationQuery } from './api'
import { ConversationHeaderBar } from './ConversationHeaderBar'
import { ConversationSidebar } from './ConversationSidebar'
import { MessageThread } from './MessageThread'
import { ReplyBox } from './ReplyBox'
import { NotesPanel } from './NotesPanel'
import { TransferHistoryPanel } from './TransferHistoryPanel'

/** Wide enough for the status/queue/assignment controls the panel holds
 * without becoming a second workspace. */
const DETAILS_PANEL_WIDTH = 340

/**
 * One conversation: what it is, what state it is in, and the reply box.
 *
 * A pane rather than a page. It renders inside the Inbox workspace beside
 * the list on a wide screen, and on its own below that breakpoint — which
 * is why the conversation id can arrive either as a prop or from the
 * route, and why the back button only exists when there is somewhere to
 * go back to.
 *
 * The facts an agent needs before replying — who, what state, how long,
 * and the actions — are in `ConversationHeaderBar`, permanently on
 * screen. They used to be in the drawer below, three clicks away behind
 * a `⋮`. The drawer kept the things that are genuinely occasional:
 * changing the status or the queue, and the AI summary.
 */
export function ConversationViewPage({
  conversationId: conversationIdProp,
  onBack,
}: {
  conversationId?: string
  onBack?: () => void
} = {}) {
  const { t } = useTranslation('conversationsCore')
  const params = useParams<{ conversationId: string }>()
  const conversationId = conversationIdProp ?? params.conversationId
  const [tab, setTab] = useState<'messages' | 'notes' | 'transfers'>('messages')
  const [detailsOpen, setDetailsOpen] = useState(false)

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
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <ConversationHeaderBar
        conversation={conversation}
        customerName={customerQuery.data?.full_name ?? null}
        customerRatingAverage={customerQuery.data?.rating_average ?? null}
        customerRatingCount={customerQuery.data?.rating_count ?? 0}
        onOpenDetails={() => setDetailsOpen(true)}
        onBack={onBack}
      />

      <Box
        sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0, minHeight: 0 }}
      >
        <Tabs
          value={tab}
          onChange={(_event, value) => setTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: 'divider', minHeight: 40, flexShrink: 0 }}
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

      {/* On demand, never permanent. As a temporary right-anchored Drawer
          it overlays instead of reflowing, so opening and closing it never
          resizes the message thread. `keepMounted` so its data isn't
          refetched on every open. */}
      <Drawer
        anchor="right"
        open={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        ModalProps={{ keepMounted: true }}
        slotProps={{
          paper: {
            sx: {
              width: { xs: '100%', sm: DETAILS_PANEL_WIDTH },
              display: 'flex',
              flexDirection: 'column',
            },
          },
        }}
      >
        <Stack
          direction="row"
          sx={{
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 2,
            py: 1.5,
            borderBottom: 1,
            borderColor: 'divider',
            flexShrink: 0,
          }}
        >
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('ConversationViewPage.conversationDetails')}
          </Typography>
          <IconButton
            onClick={() => setDetailsOpen(false)}
            aria-label={t('ConversationViewPage.closeDetailsAriaLabel')}
          >
            <CloseIcon />
          </IconButton>
        </Stack>
        {/* The panel scrolls on its own, like every other column in this
            workspace — a long details panel must never scroll the page. */}
        <Box sx={{ overflowY: 'auto', minHeight: 0, flexGrow: 1 }}>
          <ConversationSidebar
            conversation={conversation}
            customerName={customerQuery.data?.full_name ?? t('ConversationViewPage.emptyValue')}
            customerRatingAverage={customerQuery.data?.rating_average ?? null}
            customerRatingCount={customerQuery.data?.rating_count ?? 0}
          />
        </Box>
      </Drawer>
    </Box>
  )
}
