import { Box, Button, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'

export function ForbiddenPage() {
  return (
    <Box sx={{ textAlign: 'center', mt: 8 }}>
      <Typography variant="h3" sx={{ fontWeight: 700 }} gutterBottom>
        403
      </Typography>
      <Typography variant="body1" color="text.secondary" gutterBottom>
        You don't have permission to view this page. Ask a company admin if you believe this is a
        mistake.
      </Typography>
      <Button component={RouterLink} to="/" variant="contained" sx={{ mt: 2 }}>
        Back to dashboard
      </Button>
    </Box>
  )
}
