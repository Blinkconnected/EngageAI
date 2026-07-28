import { Box, List, ListItem, ListItemButton, ListItemText, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAllQueuesQuery } from '../queues/api'
import { CONVERSATION_STATUSES, type ConversationStatus } from './types'

// Maps each status to the i18n key holding its label — the label itself
// can't live in this module-scope map since translation needs `t`, which
// is only available inside the component.
const STATUS_LABEL_KEY: Record<ConversationStatus, string> = {
  open: 'tabOpen',
  pending: 'tabPending',
  resolved: 'tabResolved',
  closed: 'tabClosed',
}

export interface ConversationFilters {
  status: ConversationStatus
  queueId: string | null
}

/**
 * The workspace's dedicated **Filters & Queues** column — the second of
 * the five (nav | filters | list | conversation | details).
 *
 * Deliberately its own column rather than tabs above the conversation
 * list: filters are navigation, not a property of the list, and an
 * enterprise workspace keeps navigation persistently visible instead of
 * stacking it on top of the thing it filters (which also costs the list
 * vertical space it needs for rows). This column never scrolls with
 * anything else — it is `flexShrink: 0` with its own `overflowY: auto`,
 * so a long queue list scrolls here and nowhere else.
 */
export function ConversationFiltersPanel({
  filters,
  onChange,
}: {
  filters: ConversationFilters
  onChange: (filters: ConversationFilters) => void
}) {
  const { t } = useTranslation('conversationsCore')
  const queuesQuery = useAllQueuesQuery()

  return (
    <Box
      component="nav"
      aria-label={t('ConversationFiltersPanel.ariaLabel')}
      sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}
    >
      {/* The column's own scroll region. Everything inside scrolls here
          and only here — scrolling this list never moves the
          conversation list, the message thread, or the details panel. */}
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto', py: 1 }}>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ px: 2, display: 'block', lineHeight: 2 }}
        >
          {t('ConversationFiltersPanel.statusHeading')}
        </Typography>
        <List dense disablePadding>
          {CONVERSATION_STATUSES.map((status) => (
            // ListItem wrapper, not a bare ListItemButton: MUI renders
            // the button as a <div role="button">, and a <ul> may only
            // directly contain <li> (axe "list" rule).
            <ListItem key={status} disablePadding>
              <ListItemButton
                selected={filters.status === status}
                onClick={() => onChange({ ...filters, status })}
              >
                <ListItemText primary={t(`InboxPage.${STATUS_LABEL_KEY[status]}`)} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>

        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ px: 2, mt: 2, display: 'block', lineHeight: 2 }}
        >
          {t('ConversationFiltersPanel.queuesHeading')}
        </Typography>
        <List dense disablePadding>
          <ListItem disablePadding>
            <ListItemButton
              selected={filters.queueId === null}
              onClick={() => onChange({ ...filters, queueId: null })}
            >
              <ListItemText primary={t('ConversationFiltersPanel.allQueuesOption')} />
            </ListItemButton>
          </ListItem>
          {queuesQuery.data?.map((queue) => (
            <ListItem key={queue.id} disablePadding>
              <ListItemButton
                selected={filters.queueId === queue.id}
                onClick={() => onChange({ ...filters, queueId: queue.id })}
              >
                <ListItemText primary={queue.name} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Box>
    </Box>
  )
}
