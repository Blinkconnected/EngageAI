import { memo } from 'react'
import { Box, Collapse, IconButton, Stack, Typography } from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'
import { TimelineHeader } from './TimelineHeader'
import { TimelineIcon } from './TimelineIcon'
import { TimelineImpact } from './TimelineImpact'
import { TimelineMetadata } from './TimelineMetadata'
import { TimelineWhy } from './TimelineWhy'
import type { TimelineEvent as TimelineEventModel } from './types'

export interface TimelineEventProps {
  event: TimelineEventModel
  expanded: boolean
  onToggle: (key: string) => void
  eventKey: string
  developerMode: boolean
  /** Last row draws no rail below it, so the line ends with the story. */
  last: boolean
}

/** One event, and everything it can say about itself.
 *
 * Memoised on its own props: a thousand-event timeline re-renders on every
 * keystroke in the search box otherwise, and the list is the one part of
 * this screen that has to stay responsive while somebody types.
 */
function TimelineEventRow({
  event,
  expanded,
  onToggle,
  eventKey,
  developerMode,
  last,
}: TimelineEventProps) {
  const { t } = useTranslation('inspector')
  const hasMore = event.why.length > 0 || event.impact.length > 0 || developerMode
  const panelId = `timeline-panel-${eventKey}`

  return (
    <Box component="li" sx={{ display: 'flex', gap: 1.5, listStyle: 'none' }}>
      {/* The rail: icon plus the line connecting this event to the next. */}
      <Stack sx={{ alignItems: 'center', flexShrink: 0 }}>
        <TimelineIcon actorKind={event.actor_kind} severity={event.severity} />
        {!last ? (
          <Box sx={{ width: '1px', flexGrow: 1, bgcolor: 'divider', minHeight: 12 }} />
        ) : null}
      </Stack>

      <Box sx={{ flexGrow: 1, minWidth: 0, pb: last ? 0 : 2 }}>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'flex-start' }}>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <TimelineHeader event={event} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
              {event.detail}
            </Typography>
          </Box>
          {hasMore ? (
            <IconButton
              size="small"
              onClick={() => onToggle(eventKey)}
              aria-expanded={expanded}
              aria-controls={panelId}
              aria-label={
                expanded
                  ? t('event.collapseAria', { title: event.title })
                  : t('event.expandAria', { title: event.title })
              }
              sx={{
                transition: 'transform 150ms',
                transform: expanded ? 'rotate(180deg)' : 'none',
                '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
              }}
            >
              <ExpandMoreIcon fontSize="small" />
            </IconButton>
          ) : null}
        </Stack>

        {hasMore ? (
          <Collapse in={expanded} unmountOnExit>
            <Stack
              id={panelId}
              spacing={1.5}
              sx={{
                mt: 1,
                p: 1.5,
                borderRadius: 1,
                bgcolor: 'action.hover',
                border: 1,
                borderColor: 'divider',
              }}
            >
              <TimelineWhy why={event.why} />
              <TimelineImpact impact={event.impact} />
              {developerMode ? <TimelineMetadata event={event} /> : null}
            </Stack>
          </Collapse>
        ) : null}
      </Box>
    </Box>
  )
}

export const TimelineEventItem = memo(TimelineEventRow)
