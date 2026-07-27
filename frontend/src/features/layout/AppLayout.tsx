import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Alert,
  AppBar,
  Avatar,
  Box,
  Divider,
  Drawer,
  IconButton,
  Link,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Toolbar,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import TranslateIcon from '@mui/icons-material/Translate'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlineOutlined'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useLanguageSync } from '../../i18n/useLanguageSync'
import { setDirection, toggleThemeMode } from '../ui/uiSlice'
import { useAllAgentsQuery, useUpdateOwnAvailabilityMutation } from '../agents/api'
import type { SelfAvailabilityStatus } from '../agents/types'
import { useLogout } from '../auth/api'
import { useCurrentUserQuery } from '../session/api'
import { useCompanyLogoUrl, useCompanyQuery, useIsOnboardingIncomplete } from '../company/api'
import { NotificationBell } from '../notifications/NotificationBell'
import { NotificationToastProvider } from '../notifications/NotificationToastProvider'
import { RealtimeProvider } from '../realtime/RealtimeProvider'
import { Footer } from '../../shared/components/Footer'
import { OfflineBanner } from '../../shared/components/OfflineBanner'
import { SideNav } from './SideNav'

const DRAWER_WIDTH = 260

export function AppLayout() {
  const { t } = useTranslation('layout')
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'))
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [userMenuAnchor, setUserMenuAnchor] = useState<HTMLElement | null>(null)

  const dispatch = useAppDispatch()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const direction = useAppSelector((state) => state.ui.direction)
  const { data: currentUser } = useCurrentUserQuery()
  const { data: company } = useCompanyQuery()
  useLanguageSync(company?.settings.language)
  const { hasPermission } = usePermissions()
  const onboardingIncomplete = useIsOnboardingIncomplete()
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()
  const showSetupBanner =
    onboardingIncomplete && hasPermission('company.manage') && location.pathname !== '/onboarding'

  // Self-service availability (Online/Away/Busy) — deliberately not gated
  // by any permission (see useUpdateOwnAvailabilityMutation's docstring):
  // any authenticated agent may set their own status. Gated only by
  // actually *having* an Agent profile (a pure Owner who never became one
  // has nothing to set — PATCH /agents/me/status would 404).
  const myAgentsQuery = useAllAgentsQuery()
  const myAgent = myAgentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)
  const updateAvailabilityMutation = useUpdateOwnAvailabilityMutation()

  const drawerContent = <SideNav onNavigate={() => setMobileNavOpen(false)} />
  const logoQuery = useCompanyLogoUrl(company?.settings.branding?.logo_key)

  return (
    <NotificationToastProvider>
      <RealtimeProvider>
        <Box sx={{ display: 'flex', minHeight: '100%' }}>
          <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
            {isDesktop ? (
              <Drawer
                variant="permanent"
                open
                sx={{
                  '& .MuiDrawer-paper': {
                    width: DRAWER_WIDTH,
                    boxSizing: 'border-box',
                    borderRight: 1,
                    borderColor: 'divider',
                  },
                }}
              >
                {drawerContent}
              </Drawer>
            ) : (
              <Drawer
                variant="temporary"
                open={mobileNavOpen}
                onClose={() => setMobileNavOpen(false)}
                ModalProps={{ keepMounted: true }}
                sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' } }}
              >
                {drawerContent}
              </Drawer>
            )}
          </Box>

          <Box sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0 }}>
            <OfflineBanner />
            <AppBar
              position="static"
              color="default"
              elevation={0}
              sx={{ borderBottom: 1, borderColor: 'divider' }}
            >
              <Toolbar>
                {!isDesktop && (
                  <IconButton
                    edge="start"
                    aria-label={t('AppLayout.openNavigationMenu')}
                    onClick={() => setMobileNavOpen(true)}
                    sx={{ mr: 1 }}
                  >
                    <MenuIcon />
                  </IconButton>
                )}
                {logoQuery.data && (
                  <Box
                    component="img"
                    src={logoQuery.data}
                    alt={t('AppLayout.companyLogoAlt', {
                      companyName: currentUser?.company.name ?? t('AppLayout.companyFallback'),
                    })}
                    sx={{ height: 28, width: 28, mr: 1, borderRadius: 0.5, objectFit: 'contain' }}
                  />
                )}
                <Typography
                  variant="h6"
                  component="div"
                  noWrap
                  sx={{ flexGrow: 1, minWidth: 0, fontWeight: 600 }}
                >
                  {currentUser?.company.name ?? t('AppLayout.appName')}
                </Typography>
                <NotificationBell />
                <Tooltip title={t('AppLayout.toggleLanguageDirectionTooltip')}>
                  <IconButton
                    onClick={() => dispatch(setDirection(direction === 'ltr' ? 'rtl' : 'ltr'))}
                    aria-label={t('AppLayout.toggleDirectionAriaLabel')}
                  >
                    <TranslateIcon />
                  </IconButton>
                </Tooltip>
                <Tooltip title={t('AppLayout.toggleDarkModeTooltip')}>
                  <IconButton
                    onClick={() => dispatch(toggleThemeMode())}
                    aria-label={t('AppLayout.toggleThemeAriaLabel')}
                  >
                    {themeMode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
                  </IconButton>
                </Tooltip>
                <Tooltip title={t('AppLayout.accountTooltip')}>
                  <IconButton
                    onClick={(event) => setUserMenuAnchor(event.currentTarget)}
                    aria-label={t('AppLayout.accountMenuAriaLabel')}
                    aria-haspopup="true"
                    sx={{ ml: 1 }}
                  >
                    <Avatar sx={{ width: 32, height: 32, fontSize: '0.9rem' }}>
                      {currentUser?.full_name?.charAt(0).toUpperCase() ?? '?'}
                    </Avatar>
                  </IconButton>
                </Tooltip>
                <Menu
                  anchorEl={userMenuAnchor}
                  open={Boolean(userMenuAnchor)}
                  onClose={() => setUserMenuAnchor(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                  transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                >
                  {currentUser && (
                    <Box sx={{ px: 2, py: 1, minWidth: 200 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                        {currentUser.full_name}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {currentUser.email}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {currentUser.roles.join(', ')}
                      </Typography>
                    </Box>
                  )}
                  {myAgent && (
                    <Box sx={{ px: 2, pb: 1 }}>
                      <Typography
                        id="availability-status-label"
                        variant="caption"
                        color="text.secondary"
                        component="div"
                        sx={{ mb: 0.5 }}
                      >
                        {t('AppLayout.statusLabel')}
                        {myAgent.status === 'offline' ? t('AppLayout.statusOfflineSuffix') : ''}
                      </Typography>
                      <ToggleButtonGroup
                        size="small"
                        fullWidth
                        exclusive
                        aria-labelledby="availability-status-label"
                        value={myAgent.status === 'offline' ? null : myAgent.status}
                        onChange={(_event, value: SelfAvailabilityStatus | null) => {
                          if (value) updateAvailabilityMutation.mutate(value)
                        }}
                      >
                        <ToggleButton value="online">{t('AppLayout.onlineStatus')}</ToggleButton>
                        <ToggleButton value="away">{t('AppLayout.awayStatus')}</ToggleButton>
                        <ToggleButton value="busy">{t('AppLayout.busyStatus')}</ToggleButton>
                      </ToggleButtonGroup>
                    </Box>
                  )}
                  <Divider />
                  <MenuItem
                    onClick={() => {
                      setUserMenuAnchor(null)
                      navigate('/profile')
                    }}
                  >
                    <ListItemIcon>
                      <PersonOutlineIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>{t('AppLayout.myProfile')}</ListItemText>
                  </MenuItem>
                  <MenuItem
                    onClick={() => {
                      setUserMenuAnchor(null)
                      void logout()
                    }}
                  >
                    <ListItemIcon>
                      <LogoutIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>{t('AppLayout.signOut')}</ListItemText>
                  </MenuItem>
                </Menu>
              </Toolbar>
            </AppBar>
            <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
              {showSetupBanner && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  {t('AppLayout.setupBannerMessage')}{' '}
                  <Link component={RouterLink} to="/onboarding">
                    {t('AppLayout.setupBannerLink')}
                  </Link>
                </Alert>
              )}
              <Outlet />
            </Box>
            <Footer />
          </Box>
        </Box>
      </RealtimeProvider>
    </NotificationToastProvider>
  )
}
