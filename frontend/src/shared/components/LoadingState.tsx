import { Box, CircularProgress, Typography } from '@mui/material'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <Box
      sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, py: 6 }}
      role="status"
    >
      <CircularProgress aria-label={label} />
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
    </Box>
  )
}
