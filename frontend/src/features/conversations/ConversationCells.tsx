import type { ReactElement, ReactNode } from 'react'
import { Avatar, Badge, Box, Chip, Skeleton, Tooltip, Typography } from '@mui/material'
import WhatsAppIcon from '@mui/icons-material/WhatsApp'
import TelegramIcon from '@mui/icons-material/Telegram'
import FacebookIcon from '@mui/icons-material/Facebook'
import InstagramIcon from '@mui/icons-material/Instagram'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import SmsOutlinedIcon from '@mui/icons-material/SmsOutlined'
import ChatBubbleOutlinedIcon from '@mui/icons-material/ChatBubbleOutlined'
import ExtensionOutlinedIcon from '@mui/icons-material/ExtensionOutlined'
import ErrorOutlineOutlinedIcon from '@mui/icons-material/ErrorOutlineOutlined'
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined'
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import { useTranslation } from 'react-i18next'
import { useCustomerQuery } from '../customers/api'
import { channelTypeLabel } from '../channels/types'
import type { Conversation, ConversationPriority, SlaHealth } from './types'

/** One brand color + icon per registered channel type (see
 * channels/types.ts's CHANNEL_TYPES) — lets an agent recognize the
 * channel from shape/color alone, the way Freshdesk/Intercom do, without
 * reading the label text. Falls back to a generic chat icon for
 * plugin-defined channel types this map doesn't know about yet. */
const CHANNEL_ICONS: Record<string, { icon: ReactNode; color: string }> = {
  whatsapp: { icon: <WhatsAppIcon fontSize="small" />, color: '#25D366' },
  telegram: { icon: <TelegramIcon fontSize="small" />, color: '#26A5E4' },
  messenger: { icon: <FacebookIcon fontSize="small" />, color: '#0866FF' },
  instagram: { icon: <InstagramIcon fontSize="small" />, color: '#E4405F' },
  email: { icon: <EmailOutlinedIcon fontSize="small" />, color: '#6B7280' },
  sms: { icon: <SmsOutlinedIcon fontSize="small" />, color: '#8B5CF6' },
  web_chat: { icon: <ChatBubbleOutlinedIcon fontSize="small" />, color: '#F59E0B' },
}

export function ChannelIcon({ channelType }: { channelType: string }) {
  const { t } = useTranslation('conversationsCore')
  const entry = CHANNEL_ICONS[channelType]
  // An empty type means the conversation's channel config couldn't be
  // resolved at all (see ChannelCell) — the badge still renders, but
  // labelling it with the empty string would leave it with no accessible
  // name whatsoever.
  const label = channelType ? channelTypeLabel(channelType) : t('InboxPage.unknownChannelValue')
  return (
    <Tooltip title={label}>
      <Box
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: '50%',
          bgcolor: entry ? `${entry.color}1f` : 'action.selected',
          color: entry?.color ?? 'text.secondary',
          flexShrink: 0,
        }}
        aria-label={label}
      >
        {entry?.icon ?? <ExtensionOutlinedIcon fontSize="small" />}
      </Box>
    </Tooltip>
  )
}

/** The channel badge plus the channel's own name. The icon carries the
 * *type* at a glance, but a company routinely runs several channels of
 * the same type (two WhatsApp numbers, a support and a sales inbox), so
 * the brand mark alone never says which line a conversation actually
 * arrived on — the label does, using the same `display_name` the
 * conversation detail sidebar shows. */
export function ChannelCell({
  channelType,
  displayName,
  isPending = false,
}: {
  channelType: string | null
  displayName: string | null
  isPending?: boolean
}) {
  const { t } = useTranslation('conversationsCore')

  // The channel list is a separate request from the conversation list, so
  // rows routinely render before it lands — a skeleton avoids flashing
  // "Unknown channel" on every row for the width of that round trip.
  if (isPending) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
        <Skeleton variant="circular" width={28} height={28} />
        <Skeleton width={110} />
      </Box>
    )
  }

  // Deleting a channel is a soft delete and keeps its conversations, so an
  // id that resolves to nothing is a real state to render, not an error.
  const label = displayName ?? t('InboxPage.unknownChannelValue')

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
      <ChannelIcon channelType={channelType ?? ''} />
      <Typography variant="body2" noWrap sx={{ minWidth: 0 }} title={label}>
        {label}
      </Typography>
    </Box>
  )
}

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return `${parts[0]![0]}${parts[parts.length - 1]![0]}`.toUpperCase()
}

// A small fixed palette keyed by a hash of the name, so the same customer
// always gets the same color across renders/pages without needing a
// dedicated backend field for it.
const AVATAR_PALETTE = ['#2563EB', '#7C3AED', '#DB2777', '#D97706', '#059669', '#0891B2', '#DC2626']

function avatarColorFor(seed: string): string {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length]!
}

/** Customer identity + unread badge combined into one glanceable cell —
 * the unread dot is anchored to the avatar (not a separate column) so an
 * agent's eye only has one place to check for "is there something new
 * here." */
export function CustomerIdentityCell({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation('conversationsCore')
  const customerQuery = useCustomerQuery(conversation.customer_id)

  if (customerQuery.isPending) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0 }}>
        <Skeleton variant="circular" width={32} height={32} />
        <Skeleton width={120} />
      </Box>
    )
  }

  const name = customerQuery.data?.full_name ?? conversation.customer_id
  const hasUnread = conversation.unread_count > 0

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0 }}>
      <Badge
        overlap="circular"
        variant={hasUnread ? 'standard' : undefined}
        badgeContent={hasUnread ? conversation.unread_count : undefined}
        max={9}
        color="primary"
        aria-label={
          hasUnread
            ? t('InboxPage.unreadBadgeAriaLabel', { count: conversation.unread_count })
            : undefined
        }
      >
        <Avatar
          sx={{
            width: 32,
            height: 32,
            fontSize: '0.8rem',
            fontWeight: 600,
            bgcolor: avatarColorFor(name),
          }}
        >
          {initialsFromName(name)}
        </Avatar>
      </Badge>
      <Typography
        variant="body2"
        noWrap
        sx={{ fontWeight: hasUnread ? 700 : 400, minWidth: 0 }}
        title={name}
      >
        {name}
      </Typography>
    </Box>
  )
}

const PRIORITY_COLOR: Record<ConversationPriority, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  normal: 'info',
  high: 'warning',
  urgent: 'error',
}

/** Deliberately non-interactive here (a Chip, not a Select) — priority is
 * edited from the conversation detail sidebar, not inline from the row,
 * matching how status/queue are already handled elsewhere in the Inbox. */
export function PriorityBadge({ priority }: { priority: ConversationPriority }) {
  const { t } = useTranslation('conversationsCore')
  if (priority === 'normal') {
    // Normal is the default state of every conversation — showing a chip
    // for it on every single row would be pure visual noise for the
    // common case. Only deviations from normal earn a badge.
    return null
  }
  return (
    <Chip
      size="small"
      label={t(`InboxPage.priority.${priority}`)}
      color={PRIORITY_COLOR[priority]}
      variant={priority === 'urgent' ? 'filled' : 'outlined'}
    />
  )
}

/** Colour, icon and severity for each band. The three that show a chip
 * are deliberately distinguishable by icon as well as colour: an Inbox
 * whose only urgency signal is red/amber is unreadable to the ~8% of men
 * with a red-green deficiency, and this is the one column they most need
 * to read. */
const HEALTH_STYLE: Record<
  Exclude<SlaHealth, 'healthy'>,
  { color: 'error' | 'warning'; variant: 'filled' | 'outlined'; icon: ReactElement }
> = {
  breached: {
    color: 'error',
    variant: 'filled',
    icon: <ErrorOutlineOutlinedIcon fontSize="small" />,
  },
  at_risk: {
    color: 'warning',
    variant: 'filled',
    icon: <ReportProblemOutlinedIcon fontSize="small" />,
  },
  attention: {
    color: 'warning',
    variant: 'outlined',
    icon: <ScheduleOutlinedIcon fontSize="small" />,
  },
}

/** The primary SLA visualisation: one reading per conversation, not four
 * timers. Four timers side by side is a report; one band is a decision.
 *
 * Shows nothing at all for `healthy`, which is most rows most of the
 * time. That includes a conversation paused waiting on the customer — the
 * business is not late while the ball is with them, and an Inbox that
 * reddened those rows would teach agents to ignore red.
 *
 * Replaces an earlier indicator that read the SLA Builder's
 * breached_at/warned_at columns directly. Those columns describe one
 * policy target each; this describes the conversation. */
export function SlaIndicator({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation('conversationsCore')
  const health = conversation.sla_health
  if (!health || health === 'healthy') return null

  const style = HEALTH_STYLE[health]
  if (!style) return null

  return (
    <Tooltip title={t(`InboxPage.slaHealth.${health}.label`)}>
      <Chip
        size="small"
        icon={style.icon}
        label={t(`InboxPage.slaHealth.${health}.short`)}
        color={style.color}
        variant={style.variant}
      />
    </Tooltip>
  )
}

/** A compact "AI is handling this" signal — distinct from every other
 * badge (rounded rectangle, not a pill chip) so it never gets confused
 * with a human assignment at a glance. */
export function AutopilotBadge() {
  const { t } = useTranslation('conversationsCore')
  return (
    <Tooltip title={t('InboxPage.autopilotActiveTooltip')}>
      <Chip
        size="small"
        icon={<SmartToyOutlinedIcon fontSize="small" />}
        label={t('InboxPage.autopilotActiveShort')}
        sx={{
          bgcolor: 'secondary.main',
          color: 'secondary.contrastText',
          '& .MuiChip-icon': { color: 'inherit' },
        }}
      />
    </Tooltip>
  )
}
