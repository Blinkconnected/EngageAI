import { Card, CardContent, Grid, Typography } from '@mui/material'

export function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
      <Card variant="outlined">
        <CardContent>
          <Typography color="text.secondary" gutterBottom>
            {label}
          </Typography>
          <Typography variant="h4" component="p">
            {value}
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  )
}
