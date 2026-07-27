import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, Button, Chip, Paper, Stack, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useRealtime } from '../realtime/context'
import { AttachmentList } from './AttachmentList'
import { useMessagesQuery } from './api'
import type { Message } from './types'

const PAGE_STEP = 20
// The backend caps page_size at 100 (see docs/api/README.md's Pagination
// section) — beyond that, "load older" would need real offset-based
// paging instead of a growing page_size. Not built yet: a single
// conversation with 100+ messages is rare enough that this is a
// documented, honest limit rather than silently missing history.
const MAX_VISIBLE = 100

function MessageBubble({ message, conversationId }: { message: Message; conversationId: string }) {
  const { t } = useTranslation('conversationsCore')
  const isOutbound = message.direction === 'outbound'
  return (
    <Box sx={{ display: 'flex', justifyContent: isOutbound ? 'flex-end' : 'flex-start' }}>
      <Paper
        variant="outlined"
        sx={{
          p: 1.5,
          maxWidth: '70%',
          bgcolor: isOutbound ? 'primary.main' : 'background.paper',
          color: isOutbound ? 'primary.contrastText' : 'text.primary',
        }}
      >
        {message.message_type === 'system' ? (
          <Typography variant="body2" sx={{ fontStyle: 'italic' }}>
            {message.body}
          </Typography>
        ) : (
          <>
            {message.body && (
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {message.body}
              </Typography>
            )}
            <AttachmentList conversationId={conversationId} attachments={message.attachments} />
          </>
        )}
        <Stack direction="row" spacing={1} sx={{ mt: 0.5, alignItems: 'center' }}>
          <Typography variant="caption" sx={{ opacity: 0.8 }}>
            {formatRelativeTime(message.created_at)}
          </Typography>
          {isOutbound && message.status === 'failed' && (
            <Chip label={t('MessageThread.failedToSendLabel')} size="small" color="error" />
          )}
          {isOutbound && message.delivery_status === 'delivered' && (
            <Typography variant="caption" sx={{ opacity: 0.8 }}>
              {t('MessageThread.deliveredLabel')}
            </Typography>
          )}
        </Stack>
        {isOutbound && message.status === 'failed' && (
          // The failure reason as plain visible text, not only a hover
          // Tooltip on a non-focusable Chip — a keyboard-only or
          // screen-reader agent needs this to decide whether to retry,
          // edit, or escalate, the same info a sighted mouse user already
          // gets on hover.
          <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.25 }}>
            {typeof message.message_metadata.error === 'string'
              ? message.message_metadata.error
              : t('MessageThread.genericErrorFallback')}
          </Typography>
        )}
      </Paper>
    </Box>
  )
}

export function MessageThread({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation('conversationsCore')
  const [visibleCount, setVisibleCount] = useState(PAGE_STEP)
  const messagesQuery = useMessagesQuery(conversationId, { page: 1, page_size: visibleCount })
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastMessageId = messagesQuery.data?.items[0]?.id
  const { isCustomerTyping } = useRealtime()
  const customerTyping = isCustomerTyping(conversationId)

  useEffect(() => {
    // Newest message is index 0 in the API's DESC order — scroll to the
    // (visually bottom) newest message on load and whenever a new one
    // arrives, but not when "load older" only reveals history above it.
    // Optional chaining on the call itself, not just the ref: jsdom (used
    // in tests) doesn't implement scrollIntoView at all, unlike a real
    // browser, so this would otherwise throw and crash the render tree.
    if (lastMessageId) bottomRef.current?.scrollIntoView?.({ block: 'end' })
  }, [lastMessageId])

  if (messagesQuery.isPending) return <LoadingState label={t('MessageThread.loadingLabel')} />
  if (messagesQuery.isError) {
    return <ErrorState error={messagesQuery.error} onRetry={() => messagesQuery.refetch()} />
  }

  const total = messagesQuery.data.total
  const hasMore = total > visibleCount && visibleCount < MAX_VISIBLE
  const orderedMessages = [...messagesQuery.data.items].reverse()

  if (orderedMessages.length === 0) {
    return (
      <>
        <EmptyState
          title={t('MessageThread.noMessagesTitle')}
          description={t('MessageThread.noMessagesDescription')}
        />
        {customerTyping && <TypingIndicator />}
      </>
    )
  }

  return (
    <Stack spacing={1.5} sx={{ flexGrow: 1, overflowY: 'auto', p: 2 }}>
      {hasMore && (
        <Button
          size="small"
          onClick={() => setVisibleCount((count) => Math.min(count + PAGE_STEP, MAX_VISIBLE))}
          sx={{ alignSelf: 'center' }}
        >
          {t('MessageThread.loadOlderButton')}
        </Button>
      )}
      {orderedMessages.map((message) => (
        <MessageBubble key={message.id} message={message} conversationId={conversationId} />
      ))}
      {customerTyping && <TypingIndicator />}
      <div ref={bottomRef} />
    </Stack>
  )
}

function TypingIndicator() {
  const { t } = useTranslation('conversationsCore')
  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontStyle: 'italic', px: 1.5 }}
        role="status"
      >
        {t('MessageThread.customerTypingLabel')}
      </Typography>
    </Box>
  )
}
