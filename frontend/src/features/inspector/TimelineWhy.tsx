import { memo } from 'react'
import { Box, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

/** Why an event happened, exactly as the backend recorded it.
 *
 * Rendered verbatim. These sentences come from the engine that made the
 * decision, and rewording them here would put a second account of events
 * beside the first.
 */
export const TimelineWhy = memo(function TimelineWhy({ why }: { why: string[] }) {
  const { t } = useTranslation('inspector')
  if (why.length === 0) return null

  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
        {t('event.why')}
      </Typography>
      <Stack component="ul" spacing={0.25} sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
        {why.map((line) => (
          <Typography key={line} component="li" variant="body2" color="text.secondary">
            {line}
          </Typography>
        ))}
      </Stack>
    </Box>
  )
})
