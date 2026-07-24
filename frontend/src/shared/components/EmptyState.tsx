import type { ReactNode } from 'react'
import { Box, Typography } from '@mui/material'
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'

interface EmptyStateProps {
  title: string
  description?: string
  icon?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        gap: 1,
        py: 6,
        px: 2,
        color: 'text.secondary',
      }}
    >
      <Box sx={{ fontSize: 40, display: 'flex', color: 'text.disabled' }}>
        {icon ?? <InboxOutlinedIcon fontSize="inherit" />}
      </Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, color: 'text.primary' }}>
        {title}
      </Typography>
      {description && <Typography variant="body2">{description}</Typography>}
      {action && <Box sx={{ mt: 1 }}>{action}</Box>}
    </Box>
  )
}
