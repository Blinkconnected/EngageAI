import { Box } from '@mui/material'
import { ChangelogPanel } from './ChangelogPanel'

/**
 * A standalone, public page (no authentication required — see
 * AppRoutes.tsx, mounted alongside /login and /register, not inside
 * AppLayout/ProtectedRoute) so anyone, including a visitor who has never
 * signed in, can see what's new. Linked from LoginPage. There is no
 * PageHeader here (that component assumes it's rendered inside
 * AppLayout's own content area) — ChangelogPanel provides its own
 * top-level heading.
 */
export function ChangelogPage() {
  return (
    <Box sx={{ minHeight: '100%', bgcolor: 'background.default', p: { xs: 2, md: 4 } }}>
      <Box sx={{ maxWidth: 900, mx: 'auto' }}>
        <ChangelogPanel />
      </Box>
    </Box>
  )
}
