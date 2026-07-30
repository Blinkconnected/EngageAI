import type { ReactNode } from 'react'
import { Box, Button, Divider, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router-dom'
import { useLogout } from '../auth/api'
import { usePlatformMeQuery } from './api'

export interface ConsoleSection {
  to: string
  label: string
  /** Matches only the exact path — for a section mounted at the console root. */
  end?: boolean
}

/**
 * Chrome shared by the operator consoles.
 *
 * Deliberately not `AppLayout`: that one's navigation is the tenant product
 * (Inbox, Customers, Reports…), none of which a platform operator can open.
 * Showing it would offer a dozen links that all 403.
 *
 * Two consoles sit on this shell — running the installation and running the
 * revenue system are different jobs, done by different people, on different
 * days. They share authority (a platform operator, outside tenant RBAC
 * entirely) but not a task, so they get one nav each rather than one nav with
 * everything on it. The `sibling` link is how an operator crosses between
 * them; it is styled apart from the sections because it leaves this console
 * rather than moving within it.
 */
export function ConsoleShell({
  title,
  subtitle,
  sections,
  sibling,
  children,
}: {
  title: string
  subtitle: string
  sections: ConsoleSection[]
  sibling: { to: string; label: string }
  children?: ReactNode
}) {
  const { t } = useTranslation('platform')
  const profileQuery = usePlatformMeQuery()
  const logout = useLogout()

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100dvh' }}>
      <Box
        component="header"
        sx={{
          px: 3,
          py: 2,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          rowGap: 1,
        }}
      >
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'baseline' }}>
          <Typography variant="h6" component="p" sx={{ fontWeight: 700 }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <Stack component="nav" direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            {sections.map((section) => (
              <Button
                key={section.to}
                component={NavLink}
                to={section.to}
                end={section.end}
                size="small"
              >
                {section.label}
              </Button>
            ))}
            {/* Separated from the sections above: this one leaves the
                console rather than navigating inside it. */}
            <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
            <Button component={NavLink} to={sibling.to} size="small" color="inherit">
              {sibling.label}
            </Button>
          </Stack>
          {profileQuery.data && (
            <Typography variant="body2" color="text.secondary">
              {profileQuery.data.email}
            </Typography>
          )}
          <Button size="small" onClick={() => logout()}>
            {t('PlatformLayout.signOut')}
          </Button>
        </Stack>
      </Box>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        {children ?? <Outlet />}
      </Box>
    </Box>
  )
}
