import { memo } from 'react'
import { Box, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

/** What happened next because of this event.
 *
 * Every line here corresponds to something the backend itself recorded
 * about *this* event. The timeline never derives impact from neighbouring
 * events and must never appear to: an earlier backend version inferred it
 * from adjacency and produced confident, wrong sentences — "AI replied"
 * credited with starting a clock that had begun before AI saw the
 * conversation. A plausible false consequence is worse than a missing one,
 * because this screen's whole value is being trusted without checking.
 */
export const TimelineImpact = memo(function TimelineImpact({ impact }: { impact: string[] }) {
  const { t } = useTranslation('inspector')
  if (impact.length === 0) return null

  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
        {t('event.impact')}
      </Typography>
      <Stack component="ul" spacing={0.25} sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
        {impact.map((line) => (
          <Typography key={line} component="li" variant="body2">
            {line}
          </Typography>
        ))}
      </Stack>
    </Box>
  )
})
