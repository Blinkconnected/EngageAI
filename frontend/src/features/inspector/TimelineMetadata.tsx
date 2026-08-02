import { memo } from 'react'
import { Box, Chip, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TimelineEvent } from './types'

/** Developer mode: the codes and identifiers behind the sentence.
 *
 * Hidden by default rather than withheld. The default reading of this
 * timeline is a story a support manager follows; an event code and a
 * decision id are what an engineer needs to correlate it with a log, and
 * showing both to everybody would bury the first in the second.
 */
export const TimelineMetadata = memo(function TimelineMetadata({
  event,
}: {
  event: TimelineEvent
}) {
  const { t } = useTranslation('inspector')

  return (
    <Box sx={{ mt: 0.5 }}>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
        {t('event.metadata')}
      </Typography>
      <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap', gap: 0.5 }}>
        {event.code ? <Chip size="small" variant="outlined" label={event.code} /> : null}
        <Chip size="small" variant="outlined" label={event.stream} />
        <Chip size="small" variant="outlined" label={event.actor_kind} />
      </Stack>
      {event.facts.length > 0 ? (
        <Box
          component="dl"
          sx={{
            display: 'grid',
            gridTemplateColumns: 'auto 1fr',
            columnGap: 1.5,
            rowGap: 0.25,
            m: 0,
            mt: 1,
          }}
        >
          {event.facts.map(([label, value]) => (
            <Box key={`${label}:${value}`} sx={{ display: 'contents' }}>
              <Typography component="dt" variant="caption" color="text.secondary">
                {label}
              </Typography>
              <Typography component="dd" variant="caption" sx={{ m: 0 }}>
                {value}
              </Typography>
            </Box>
          ))}
        </Box>
      ) : null}
      {event.decision_id ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mt: 1, fontFamily: 'monospace', wordBreak: 'break-all' }}
        >
          {t('event.decisionId')}: {event.decision_id}
        </Typography>
      ) : null}
    </Box>
  )
})
