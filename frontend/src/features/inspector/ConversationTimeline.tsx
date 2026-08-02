import { useCallback, useDeferredValue, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { TimelineEventItem } from './TimelineEvent'
import { TimelineEmptyState } from './TimelineEmptyState'
import { TimelineFilters } from './TimelineFilters'
import { TimelineSearch } from './TimelineSearch'
import { TimelineSkeleton } from './TimelineSkeleton'
import { TIMELINE_STREAMS, type TimelineEvent, type TimelineStream } from './types'

/** How many events render before the list is capped.
 *
 * Not virtualisation. A virtualised list of variable-height, expandable rows
 * needs measurement plumbing that fights the expand animation, and the
 * honest read of the data is that conversations reach hundreds of events,
 * not tens of thousands. So the list renders a bounded window and *says*
 * that it did — a silent truncation on an audit screen would be the same
 * class of lie as an invented event.
 *
 * Rows are memoised, so typing in the search box re-renders the matcher and
 * not the list.
 */
const RENDER_LIMIT = 300

function dayOf(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? '' : at.toISOString().slice(0, 10)
}

function matches(event: TimelineEvent, needle: string): boolean {
  if (!needle) return true
  const haystack = [
    event.title,
    event.detail,
    event.actor,
    event.code ?? '',
    ...event.why,
    ...event.impact,
    ...event.facts.flat(),
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(needle)
}

export interface ConversationTimelineProps {
  events: TimelineEvent[]
  /** What the platform does not know about this conversation, shown when
   * there is nothing to display — an empty section and an unrecorded one
   * are different answers. */
  gaps?: string[]
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}

/** The Conversation Story: an operational audit timeline.
 *
 * Renders exactly what the backend recorded and nothing else. It derives no
 * impact, infers no relationships between events, and assigns no severity —
 * the backend returns none, and a red row this screen invented would be
 * indistinguishable from one the platform actually flagged.
 */
export function ConversationTimeline({
  events,
  gaps = [],
  loading = false,
  error,
  onRetry,
}: ConversationTimelineProps) {
  const { t } = useTranslation('inspector')
  const [query, setQuery] = useState('')
  const [streams, setStreams] = useState<Set<TimelineStream>>(() => new Set())
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [developerMode, setDeveloperMode] = useState(false)

  // Deferred so a long list keeps up with typing: the input stays live while
  // the filtered list catches up a frame later.
  const needle = useDeferredValue(query).trim().toLowerCase()

  const counts = useMemo(() => {
    const tally: Record<string, number> = {}
    for (const stream of TIMELINE_STREAMS) tally[stream] = 0
    for (const event of events) tally[event.stream] = (tally[event.stream] ?? 0) + 1
    return tally
  }, [events])

  const visible = useMemo(
    () =>
      events.filter(
        (event) => (streams.size === 0 || streams.has(event.stream)) && matches(event, needle),
      ),
    [events, streams, needle],
  )

  const shown = useMemo(
    () => (visible.length > RENDER_LIMIT ? visible.slice(0, RENDER_LIMIT) : visible),
    [visible],
  )
  const hidden = visible.length - shown.length

  // Which rows open a new day, worked out once rather than by mutating a
  // cursor while rendering — a render-time mutation is a re-render away from
  // putting the separators in the wrong places.
  const startsDay = useMemo(() => {
    const flags: boolean[] = []
    let previous = ''
    for (const event of shown) {
      const day = dayOf(event.at)
      flags.push(day !== previous)
      previous = day
    }
    return flags
  }, [shown])

  const toggleExpanded = useCallback((key: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const toggleStream = useCallback((stream: TimelineStream) => {
    setStreams((current) => {
      const next = new Set(current)
      if (next.has(stream)) next.delete(stream)
      else next.add(stream)
      return next
    })
  }, [])

  const clearStreams = useCallback(() => setStreams(new Set()), [])

  if (error) {
    return (
      <Alert
        severity="error"
        action={
          onRetry ? (
            <Button color="inherit" size="small" onClick={onRetry}>
              {t('error.retry')}
            </Button>
          ) : undefined
        }
      >
        {t('error.body')}
      </Alert>
    )
  }

  return (
    <Stack spacing={2}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.5}
        sx={{ alignItems: { xs: 'stretch', md: 'center' } }}
      >
        <TimelineSearch value={query} onChange={setQuery} />
        <Box sx={{ flexGrow: 1 }}>
          <TimelineFilters
            selected={streams}
            counts={counts}
            onToggle={toggleStream}
            onClear={clearStreams}
          />
        </Box>
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={developerMode}
              onChange={(e) => setDeveloperMode(e.target.checked)}
            />
          }
          label={
            <Typography variant="body2" color="text.secondary">
              {t('developerMode')}
            </Typography>
          }
        />
      </Stack>

      {loading ? (
        <TimelineSkeleton />
      ) : shown.length === 0 ? (
        <TimelineEmptyState filtered={events.length > 0} gaps={gaps} />
      ) : (
        <>
          <Box
            component="ol"
            aria-label={t('timeline.label')}
            sx={{ listStyle: 'none', m: 0, p: 0 }}
          >
            {shown.map((event, index) => {
              const key = `${event.at}-${event.code ?? event.stream}-${index}`
              return (
                <Box component="li" key={key} sx={{ listStyle: 'none' }}>
                  {startsDay[index] ? (
                    <Box
                      sx={{
                        position: 'sticky',
                        top: 0,
                        zIndex: 1,
                        py: 0.75,
                        bgcolor: 'background.paper',
                      }}
                    >
                      <Divider>
                        <Typography variant="caption" color="text.secondary">
                          {new Date(event.at).toLocaleDateString(undefined, {
                            weekday: 'short',
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric',
                          })}
                        </Typography>
                      </Divider>
                    </Box>
                  ) : null}
                  <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                    <TimelineEventItem
                      event={event}
                      eventKey={key}
                      expanded={expanded.has(key)}
                      onToggle={toggleExpanded}
                      developerMode={developerMode}
                      last={index === shown.length - 1}
                    />
                  </Box>
                </Box>
              )
            })}
          </Box>
          {hidden > 0 ? (
            <Alert severity="info">{t('timeline.truncated', { count: hidden })}</Alert>
          ) : null}
        </>
      )}
    </Stack>
  )
}
