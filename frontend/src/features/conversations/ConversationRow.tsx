import { memo } from 'react'
import { Box, Button, ButtonBase, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatElapsed } from '../../shared/utils/formatElapsed'
import { ChannelIcon } from './ConversationCells'
import { isPickable } from './conversationRules'
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
 *
 * The row is a `<li>` holding two sibling buttons rather than one
 * clickable `<li role="button">`. Pick up has to be reachable from the
 * list — it is the most common action there is — and a `<button>` nested
 * inside another button is invalid markup that no screen reader reads
 * predictably.
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

export interface ConversationRowProps {
  conversation: Conversation
  channelType: string | null
  onOpen: (id: string) => void
  /** Highlights the row being read in the pane beside the list. */
  selected?: boolean
  /** Omitted when the reader has no `conversations.pick` permission, which
   * is what hides the button rather than disabling it. */
  onPick?: (id: string) => void
  pickPending?: boolean
  /** Ticking clock, owned by the list so one timer serves every row
   * instead of fifty. */
  now?: number
}

export const ConversationRow = memo(function ConversationRow({
  conversation,
  channelType,
  onOpen,
  selected = false,
  onPick,
  pickPending = false,
  now,
}: ConversationRowProps) {
  const { t } = useTranslation('conversationsCore')
  const health = conversation.sla_health
  const style = health === 'healthy' ? null : HEALTH_STYLE[health]
  const duration = formatElapsed(conversation.owner_since, now)
  const unread = conversation.unread_count > 0
  const pickable = isPickable(conversation)

  return (
    <Box
      component="li"
      sx={{
        listStyle: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        pe: 1,
        borderBottom: 1,
        borderColor: 'divider',
        // The selected row is marked by a bar on the leading edge as well
        // as a tint: a tint alone is invisible against the hover state,
        // and both are colour-only signals.
        bgcolor: selected ? 'action.selected' : undefined,
        borderInlineStart: 3,
        borderInlineStartColor: selected ? 'primary.main' : 'transparent',
        '&:hover': { bgcolor: selected ? 'action.selected' : 'action.hover' },
      }}
    >
      <ButtonBase
        onClick={() => onOpen(conversation.id)}
        aria-label={t('Inbox.rowAria', {
          customer: conversation.customer_name ?? conversation.customer_id,
          state: conversation.state_text ?? '',
        })}
        aria-current={selected ? 'true' : undefined}
        sx={{
          flexGrow: 1,
          minWidth: 0,
          display: 'block',
          textAlign: 'start',
          px: 1.5,
          py: 1.5,
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
      </ButtonBase>

      {/* Claiming work without opening it first. An agent working a
          pickup queue takes several in a row, and making each one a
          round trip through the conversation is the slow path. */}
      {onPick && pickable ? (
        <Button
          size="small"
          variant="outlined"
          disabled={pickPending}
          onClick={() => onPick(conversation.id)}
          sx={{ flexShrink: 0 }}
        >
          {t('ConversationSidebar.pickButton')}
        </Button>
      ) : null}
    </Box>
  )
})
