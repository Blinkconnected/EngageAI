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
            {/* The only signal in the bubble itself of who sent it — the
                rest (alignment, background colour) is decorative and
                fails WCAG 1.4.1 (Use of Color) on its own: a screen
                reader or a user who can't distinguish the two colours
                would otherwise read an undifferentiated run of message
                bodies with no way to tell customer from agent. */}
            <Typography
              variant="caption"
              sx={{ display: 'block', fontWeight: 600, opacity: 0.8, mb: 0.25 }}
            >
              {isOutbound ? t('MessageThread.senderAgent') : t('MessageThread.senderCustomer')}
            </Typography>
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
          {isOutbound && message.message_metadata.is_ai_generated === true && (
            // The only signal anywhere (transcript, API, audit log) that
            // this reply had no human in the loop — see
            // ai_autopilot_consumer.py's send_reply(is_ai_generated=True).
            <Chip
              label={t('MessageThread.aiGeneratedLabel')}
              size="small"
              color="info"
              variant="outlined"
            />
          )}
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

// Within this many pixels of the bottom still counts as "at the bottom"
// for auto-scroll purposes — an exact `=== 0` check would stop
// autoscrolling on the slightest sub-pixel rounding.
const STICK_TO_BOTTOM_THRESHOLD_PX = 48

export function MessageThread({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation('conversationsCore')
  const [visibleCount, setVisibleCount] = useState(PAGE_STEP)
  const messagesQuery = useMessagesQuery(conversationId, { page: 1, page_size: visibleCount })
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  // Read at the moment a new message arrives, before the DOM updates —
  // not in state, since this must never itself trigger a re-render.
  const wasNearBottomRef = useRef(true)
  const lastMessageId = messagesQuery.data?.items[0]?.id
  const { isCustomerTyping } = useRealtime()
  const customerTyping = isCustomerTyping(conversationId)

  function handleScroll() {
    const el = scrollContainerRef.current
    if (!el) return
    wasNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_TO_BOTTOM_THRESHOLD_PX
  }

  useEffect(() => {
    // Opening a conversation must always land on its newest message.
    // `wasNearBottomRef` is deliberately a ref that survives re-renders,
    // which means it also survives switching conversations in the
    // three-pane workspace (this component doesn't remount, only its
    // prop changes) — so an agent who had scrolled up reading history in
    // the previous conversation would otherwise open the next one
    // stranded mid-thread. Reset per conversation, before the
    // scroll-to-newest effect below reads it.
    wasNearBottomRef.current = true
  }, [conversationId])

  useEffect(() => {
    // Newest message is index 0 in the API's DESC order — scroll to the
    // (visually bottom) newest message on load and whenever a new one
    // arrives, but ONLY when the reader was already at/near the bottom
    // before it arrived — an agent scrolled up reading history must not
    // get yanked back down by a new message (their own reply sent from
    // another tab, a background poll, the customer's next message)
    // while they're in the middle of reading. Never fires for "load
    // older" revealing history above (that doesn't change lastMessageId)
    // or for a no-op background poll (same reasoning). Optional chaining
    // on the call itself, not just the ref: jsdom (used in tests) doesn't
    // implement scrollIntoView at all, unlike a real browser, so this
    // would otherwise throw and crash the render tree.
    if (lastMessageId && wasNearBottomRef.current) {
      bottomRef.current?.scrollIntoView?.({ block: 'end' })
    }
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
    <Stack
      ref={scrollContainerRef}
      onScroll={handleScroll}
      spacing={1.5}
      sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto', p: 2 }}
    >
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
