import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Box, IconButton, Stack, Tab, Tabs, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useCustomerQuery } from '../customers/api'
import { useRealtime } from '../realtime/context'
import { useConversationQuery } from './api'
import { ConversationSidebar } from './ConversationSidebar'
import { MessageThread } from './MessageThread'
import { ReplyBox } from './ReplyBox'
import { NotesPanel } from './NotesPanel'

export function ConversationViewPage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'messages' | 'notes'>('messages')

  const conversationQuery = useConversationQuery(conversationId)
  const customerQuery = useCustomerQuery(conversationQuery.data?.customer_id)
  const { sendTyping } = useRealtime()

  if (conversationQuery.isPending) return <LoadingState label="Loading conversation…" />
  if (conversationQuery.isError) {
    return (
      <ErrorState error={conversationQuery.error} onRetry={() => conversationQuery.refetch()} />
    )
  }

  const conversation = conversationQuery.data

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 2 }}>
        <IconButton onClick={() => navigate('/conversations')} aria-label="Back to inbox">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          {customerQuery.data?.full_name ?? 'Conversation'}
        </Typography>
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        sx={{ flexGrow: 1, minHeight: 0, border: 1, borderColor: 'divider', borderRadius: 2 }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0 }}>
          <Tabs
            value={tab}
            onChange={(_event, value) => setTab(value)}
            sx={{ borderBottom: 1, borderColor: 'divider' }}
          >
            <Tab label="Messages" value="messages" />
            <Tab label="Internal notes" value="notes" />
          </Tabs>

          {tab === 'messages' ? (
            <>
              <MessageThread conversationId={conversation.id} />
              <ReplyBox
                conversationId={conversation.id}
                onTyping={(isTyping) => sendTyping(conversation.id, isTyping)}
              />
            </>
          ) : (
            <NotesPanel conversationId={conversation.id} />
          )}
        </Box>

        <Box sx={{ borderLeft: { md: 1 }, borderTop: { xs: 1, md: 0 }, borderColor: 'divider' }}>
          <ConversationSidebar
            conversation={conversation}
            customerName={customerQuery.data?.full_name ?? '—'}
          />
        </Box>
      </Stack>
    </Box>
  )
}
