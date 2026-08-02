import { Chip, Stack } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { TIMELINE_STREAMS, type TimelineStream } from './types'

/** Filter by where an event came from.
 *
 * Counts are on the chips deliberately: "policy (0)" answers "were any
 * policies evaluated?" without the reader selecting it and finding out the
 * hard way. A filter that can only be tested by using it is a filter people
 * click through one at a time.
 */
export function TimelineFilters({
  selected,
  counts,
  onToggle,
  onClear,
}: {
  selected: Set<TimelineStream>
  counts: Record<string, number>
  onToggle: (stream: TimelineStream) => void
  onClear: () => void
}) {
  const { t } = useTranslation('inspector')
  const filtering = selected.size > 0

  return (
    <Stack
      direction="row"
      spacing={0.75}
      role="group"
      aria-label={t('filters.label')}
      sx={{ flexWrap: 'wrap', gap: 0.75 }}
    >
      <Chip
        size="small"
        label={t('filters.all')}
        color={filtering ? 'default' : 'primary'}
        variant={filtering ? 'outlined' : 'filled'}
        onClick={onClear}
        aria-pressed={!filtering}
      />
      {TIMELINE_STREAMS.map((stream) => {
        const active = selected.has(stream)
        return (
          <Chip
            key={stream}
            size="small"
            label={`${t(`stream.${stream}`)} (${counts[stream] ?? 0})`}
            color={active ? 'primary' : 'default'}
            variant={active ? 'filled' : 'outlined'}
            onClick={() => onToggle(stream)}
            aria-pressed={active}
            disabled={(counts[stream] ?? 0) === 0 && !active}
          />
        )
      })}
    </Stack>
  )
}
