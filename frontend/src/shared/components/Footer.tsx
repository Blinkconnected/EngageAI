import { Box, Typography } from '@mui/material'

export function Footer() {
  const year = new Date().getFullYear()

  return (
    <Box sx={{ py: 2, textAlign: 'center' }}>
      <Typography variant="caption" color="text.secondary">
        © Blink Engage {year}
      </Typography>
    </Box>
  )
}
