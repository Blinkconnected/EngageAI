import { Card, CardContent, Grid, Typography } from '@mui/material'

export function DashboardPage() {
  return (
    <Grid container spacing={2}>
      <Grid size={12}>
        <Typography variant="h5" sx={{ fontWeight: 600 }} gutterBottom>
          Welcome to Blink Engage
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Your omnichannel conversations, queues and analytics will appear here.
        </Typography>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 3 }}>
        <Card variant="outlined">
          <CardContent>
            <Typography color="text.secondary" gutterBottom>
              Open conversations
            </Typography>
            <Typography variant="h4">0</Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 3 }}>
        <Card variant="outlined">
          <CardContent>
            <Typography color="text.secondary" gutterBottom>
              Unassigned
            </Typography>
            <Typography variant="h4">0</Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 3 }}>
        <Card variant="outlined">
          <CardContent>
            <Typography color="text.secondary" gutterBottom>
              Avg. response time
            </Typography>
            <Typography variant="h4">—</Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 3 }}>
        <Card variant="outlined">
          <CardContent>
            <Typography color="text.secondary" gutterBottom>
              CSAT
            </Typography>
            <Typography variant="h4">—</Typography>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  )
}
