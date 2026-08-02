import { memo } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { ChannelIcon } from './ConversationCells'
import type { Conversation, SlaHealth } from './types'

/** One conversation, communicated in the order an agent decides in.
 *
 *   customer → operational state → SLA health → owner → duration
 *   → last meaningful event → last message → channel
 *
 * The last message is seventh of eight, and that is the whole reframing: an
 * agent should understand *why a conversation is in front of them* before
 * reading a word of its content. A row that opens with message text is a row
 * that makes them read in order to decide.
 *
 * Channel is last because it almost never changes what somebody does first.
 */

/** SLA health is the dominant signal, so it is the only thing on the row that
 * carries colour of its own. Priority is business importance and does not
 * compete with it — the two were sharing a cell and reading as one. */
const HEALTH_STYLE: Record<
  Exclude<SlaHealth, 'healthy'>,
  { color: 'error' | 'warning'; variant: 'filled' | 'outlined' }
> = {
  breached: { color: 'error', variant: 'filled' },
  at_risk: { color: 'warning', variant: 'filled' },
  attention: { color: 'warning', variant: 'outlined' },
}

/** How long something has been true, said the way a person says it.
 *
 * Formatted here rather than on the server: "42m" is not "٤٢ د", and the
 * server has no business choosing which one the reader gets.
 */
function since(iso: string | null): string | null {
  if (!iso) return null
  const started = new Date(iso).getTime()
  if (Number.isNaN(started)) return null
  const seconds = Math.max(0, Math.round((Date.now() - started) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${minutes % 60}m`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

export interface ConversationRowProps {
  conversation: Conversation
  channelType: string | null
  onOpen: (id: string) => void
}

export const ConversationRow = memo(function ConversationRow({
  conversation,
  channelType,
  onOpen,
}: ConversationRowProps) {
  const { t } = useTranslation('conversationsCore')
  const health = conversation.sla_health
  const style = health === 'healthy' ? null : HEALTH_STYLE[health]
  const duration = since(conversation.owner_since ?? null)
  const unread = conversation.unread_count > 0

  return (
    <Box
      component="li"
      onClick={() => onOpen(conversation.id)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen(conversation.id)
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={t('Inbox.rowAria', {
        customer: conversation.customer_name ?? conversation.customer_id,
        state: conversation.state_text ?? '',
      })}
      sx={{
        listStyle: 'none',
        px: 2,
        py: 1.5,
        borderBottom: 1,
        borderColor: 'divider',
        cursor: 'pointer',
        '&:hover': { bgcolor: 'action.hover' },
        '&:focus-visible': { outline: 2, outlineColor: 'primary.main', outlineOffset: -2 },
      }}
    >
      {/* 1. WHO */}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography
          variant="body2"
          sx={{ fontWeight: unread ? 700 : 600, minWidth: 0 }}
          noWrap
          title={conversation.customer_name ?? undefined}
        >
          {conversation.customer_name ?? conversation.customer_id}
        </Typography>

        {/* 2. WHY — the most important line on the row. */}
        {conversation.state_text ? (
          <Chip
            size="small"
            variant="outlined"
            label={conversation.state_text}
            sx={{ height: 20, fontWeight: 500 }}
          />
        ) : null}

        {/* 3. HOW URGENT — the only colour that competes for attention. */}
        {style ? (
          <Chip
            size="small"
            color={style.color}
            variant={style.variant}
            label={t(`health.${health}`)}
            sx={{ height: 20 }}
          />
        ) : null}

        {/* Business importance, and only when it is not the default: a badge
            on every row is a badge on none. */}
        {conversation.priority !== 'normal' ? (
          <Chip
            size="small"
            variant="outlined"
            label={t(`InboxPage.priority.${conversation.priority}`)}
            sx={{ height: 20 }}
          />
        ) : null}

        <Box sx={{ flexGrow: 1 }} />

        {/* 8. CHANNEL — a mark, nothing more. */}
        {channelType ? <ChannelIcon channelType={channelType} /> : null}
      </Stack>

      {/* 4. OWNER and 5. HOW LONG */}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
        {conversation.owner_label || t('Inbox.nobodyOwns')}
        {duration ? ` · ${duration}` : ''}
      </Typography>

      {/* 6. WHAT MOST RECENTLY CHANGED — what the platform decided, in the
          words the engine that decided it wrote. This is what an agent needs
          before the content: it says whether anything has moved since they
          last looked. */}
      {conversation.last_event ? (
        <Typography variant="body2" noWrap sx={{ mt: 0.5 }} title={conversation.last_event}>
          {conversation.last_event}
        </Typography>
      ) : null}
    </Box>
  )
})
