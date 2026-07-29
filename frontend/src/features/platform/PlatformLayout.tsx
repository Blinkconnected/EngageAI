import { Box, Button, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router-dom'
import { useLogout } from '../auth/api'
import { usePlatformMeQuery } from './api'

/**
 * Chrome for the platform console. Deliberately not `AppLayout`: that
 * one's navigation is the tenant product (Inbox, Customers, Reports…),
 * none of which a platform operator can open. Showing it would offer a
 * dozen links that all 403.
 */
export function PlatformLayout() {
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
            {t('PlatformLayout.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('PlatformLayout.subtitle')}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <Stack component="nav" direction="row" spacing={1}>
            <Button component={NavLink} to="/platform" end size="small">
              {t('PlatformLayout.companies')}
            </Button>
            <Button component={NavLink} to="/platform/pricing" size="small">
              {t('PlatformLayout.pricing')}
            </Button>
            <Button component={NavLink} to="/platform/mail" size="small">
              {t('PlatformLayout.mail')}
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
        <Outlet />
      </Box>
    </Box>
  )
}
