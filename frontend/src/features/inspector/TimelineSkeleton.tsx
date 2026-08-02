import { Box, Skeleton, Stack } from '@mui/material'

/** A shape that matches what arrives, so the page does not jump.
 *
 * Six rows rather than one spinner: the reader's eye settles where the
 * content will be, and a timeline that reflows on load is one they have to
 * find their place in twice.
 */
export function TimelineSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <Stack spacing={2} aria-hidden data-testid="timeline-skeleton">
      {Array.from({ length: rows }, (_, index) => (
        <Stack key={index} direction="row" spacing={1.5}>
          <Skeleton variant="circular" width={32} height={32} />
          <Box sx={{ flexGrow: 1 }}>
            <Skeleton variant="text" width="35%" />
            <Skeleton variant="text" width="70%" />
          </Box>
        </Stack>
      ))}
    </Stack>
  )
}
