import { useEffect, useRef, useState } from 'react'
import { Box, Button, Chip, Paper, Stack, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useMessagesQuery } from './api'
import type { Message } from './types'

const PAGE_STEP = 20
// The backend caps page_size at 100 (see docs/api/README.md's Pagination
// section) — beyond that, "load older" would need real offset-based
// paging instead of a growing page_size. Not built yet: a single
// conversation with 100+ messages is rare enough that this is a
// documented, honest limit rather than silently missing history.
const MAX_VISIBLE = 100

function MessageBubble({ message }: { message: Message }) {
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
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {message.body}
          </Typography>
        )}
        <Stack direction="row" spacing={1} sx={{ mt: 0.5, alignItems: 'center' }}>
          <Typography variant="caption" sx={{ opacity: 0.8 }}>
            {formatRelativeTime(message.created_at)}
          </Typography>
          {isOutbound && message.status === 'failed' && (
            <Chip label="Failed" size="small" color="error" />
          )}
          {isOutbound && message.delivery_status === 'delivered' && (
            <Typography variant="caption" sx={{ opacity: 0.8 }}>
              · Delivered
            </Typography>
          )}
        </Stack>
      </Paper>
    </Box>
  )
}

export function MessageThread({ conversationId }: { conversationId: string }) {
  const [visibleCount, setVisibleCount] = useState(PAGE_STEP)
  const messagesQuery = useMessagesQuery(conversationId, { page: 1, page_size: visibleCount })
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastMessageId = messagesQuery.data?.items[0]?.id

  useEffect(() => {
    // Newest message is index 0 in the API's DESC order — scroll to the
    // (visually bottom) newest message on load and whenever a new one
    // arrives, but not when "load older" only reveals history above it.
    // Optional chaining on the call itself, not just the ref: jsdom (used
    // in tests) doesn't implement scrollIntoView at all, unlike a real
    // browser, so this would otherwise throw and crash the render tree.
    if (lastMessageId) bottomRef.current?.scrollIntoView?.({ block: 'end' })
  }, [lastMessageId])

  if (messagesQuery.isPending) return <LoadingState label="Loading messages…" />
  if (messagesQuery.isError) {
    return <ErrorState error={messagesQuery.error} onRetry={() => messagesQuery.refetch()} />
  }

  const total = messagesQuery.data.total
  const hasMore = total > visibleCount && visibleCount < MAX_VISIBLE
  const orderedMessages = [...messagesQuery.data.items].reverse()

  if (orderedMessages.length === 0) {
    return <EmptyState title="No messages yet" description="This conversation has no messages." />
  }

  return (
    <Stack spacing={1.5} sx={{ flexGrow: 1, overflowY: 'auto', p: 2 }}>
      {hasMore && (
        <Button
          size="small"
          onClick={() => setVisibleCount((count) => Math.min(count + PAGE_STEP, MAX_VISIBLE))}
          sx={{ alignSelf: 'center' }}
        >
          Load older messages
        </Button>
      )}
      {orderedMessages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <div ref={bottomRef} />
    </Stack>
  )
}
